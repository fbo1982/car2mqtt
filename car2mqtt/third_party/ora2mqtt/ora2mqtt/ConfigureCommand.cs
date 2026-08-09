using CommandLine;
using libgwmapi.DTO.UserAuth;
using libgwmapi;
using MQTTnet.Exceptions;
using MQTTnet;
using Sharprompt;
using Sharprompt.Fluent;
using YamlDotNet.Serialization;
using ora2mqtt.Logging;
using Microsoft.Extensions.Logging;
using System.Security.Cryptography;
using System.Text;

namespace ora2mqtt
{
    [Verb("configure", HelpText = "run config file wizard")]
    public class ConfigureCommand:BaseCommand
    {
        private ILogger<ConfigureCommand> _logger;

        private static string? Env(string name) => Environment.GetEnvironmentVariable(name);
        private static bool HasEnv(string name) => !String.IsNullOrWhiteSpace(Env(name));
        private bool NonInteractive => HasEnv("ORA_ACCOUNT") && HasEnv("ORA_PASSWORD");
        private string? VerificationCode => Env("ORA_VERIFICATION_CODE");
        private string AuthFlow(Ora2MqttOptions options) =>
            (Env("ORA_AUTH_FLOW") ?? options.AuthFlow ?? "eu_mygwm_front").Trim().ToLowerInvariant();

        public async Task<int> Run(CancellationToken cancellationToken)
        {
            Setup();
            _logger = LoggerFactory.CreateLogger<ConfigureCommand>();
            Ora2MqttOptions config;
            if (!File.Exists(ConfigFile))
            {
                config = new Ora2MqttOptions
                {
                    DeviceId = Guid.NewGuid().ToString("N"),
                };
            }
            else
            {
                var deserializer = new Deserializer();
                using (var file = File.OpenText(ConfigFile))
                {
                    config = deserializer.Deserialize<Ora2MqttOptions>(file);
                }
            }
            await SaveConfigAsync(config, cancellationToken);

            SelectCountry(config);
            await SaveConfigAsync(config, cancellationToken);

            var client = ConfigureApiClient(config);

            await LoginAsync(client, config, cancellationToken);
            await SaveConfigAsync(config, cancellationToken);

            if (NonInteractive)
            {
                ConfigureMqttFromEnvironment(config);
                if (!await TestMqttAsync(config, cancellationToken))
                {
                    _logger.LogError("Mqtt connection failed in non-interactive mode");
                    return 2;
                }
            }
            else
            {
                while (!await TestMqttAsync(config, cancellationToken))
                {
                    ConfigureMqttAsync(config);
                }
            }
            await SaveConfigAsync(config, cancellationToken);

            Console.WriteLine("Configuration successful!");
            return 0;
        }

        private void SelectCountry(Ora2MqttOptions options)
        {
            if (!String.IsNullOrWhiteSpace(Env("ORA_COUNTRY")))
            {
                options.Country = Env("ORA_COUNTRY")!;
                return;
            }
            if (String.IsNullOrEmpty(options.Country))
            {
                options.Country = Prompt.Select<string>(o => o
                    .WithMessage("Please choose your country")
                    .WithItems(new[] { "DE", "GB", "EE" })
                );
            }
        }

        private async Task LoginAsync(GwmApiClient client, Ora2MqttOptions options, CancellationToken cancellationToken)
        {
            if (!String.IsNullOrEmpty(options.Account.AccessToken))
            {
                try
                {
                    client.SetAccessToken(options.Account.AccessToken);
                    await client.GetUserBaseInfoAsync(cancellationToken);
                    return;
                }
                catch (GwmApiException e)
                {
                    _logger.LogError($"Access token expired ({e.Message}). Trying to refresh token...");
                }
                var refresh = new RefreshTokenRequest
                {
                    DeviceId = options.DeviceId,
                    AccessToken = options.Account.AccessToken,
                    RefreshToken = options.Account.RefreshToken,
                };
                client.SetAccessToken("");
                try
                {
                    var response = await client.RefreshTokenAsync(refresh, cancellationToken);
                    options.Account.AccessToken = response.AccessToken;
                    options.Account.RefreshToken = response.RefreshToken;
                    return;
                }
                catch (GwmApiException e)
                {
                    _logger.LogError($"Token refresh failed: GWM code={e.Code}; {e.Message}");
                }
            }
            var account = NonInteractive ? Env("ORA_ACCOUNT")! : Prompt.Input<string>("Please enter your mail address");
            var password = NonInteractive ? Env("ORA_PASSWORD")! : Prompt.Password("Please enter your password");
            var authFlow = AuthFlow(options);
            var useEuMyGwmFront = String.Equals(authFlow, "eu_mygwm_front", StringComparison.OrdinalIgnoreCase);
            var useMyGwm13 = String.Equals(authFlow, "mygwm13", StringComparison.OrdinalIgnoreCase);
            var useEuVerifyCode = String.Equals(authFlow, "eu_verifycode", StringComparison.OrdinalIgnoreCase);
            options.AuthFlow = useEuMyGwmFront ? "eu_mygwm_front" :
                (useMyGwm13 ? "mygwm13" : (useEuVerifyCode ? "eu_verifycode" : "legacy"));

            // Vehicle traffic stays on the existing EU gateway profile for now.  The new
            // My GWM authentication probe gets its own front-service transport so the OTP
            // and device context never cross the legacy ORA H5 session.
            client.UseLegacyOraProfile();
            if (useEuMyGwmFront)
            {
                client.UseMyGwmEuFrontProfile(options.Country, GwmApiClient.MyGwmEuFrontRouteIds[0]);
            }
            else if (useMyGwm13)
            {
                // Experimental only: v1.2.38 showed EU rejecting this app-gateway identity.
                client.UseMyGwm13Profile();
            }

            var request = new LoginAccountRequest
            {
                Country = options.Country,
                IsEncrypt = false,
                DeviceId = options.DeviceId,
                Model = "ora2mqtt",
                PushToken = "",
                Account = account,
                Password = password
            };
            var frontRequest = new MyGwmEuFrontLoginRequest
            {
                Account = account,
                Password = Md5Lower(password),
                DeviceId = options.DeviceId
            };
            try
            {
                LoginAccountResponse token;
                if (useEuMyGwmFront)
                {
                    token = null!;
                    HttpRequestException? lastRouteHttpException = null;
                    foreach (var routeId in GwmApiClient.MyGwmEuFrontRouteIds)
                    {
                        client.UseMyGwmEuFrontProfile(options.Country, routeId);
                        _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=route_probe transport=eu-front-service endpoint=userAuth/loginAccount terminal=GW_PC_GWM brand=6 device_context=persistent route={routeId} sms_sent=false");
                        try
                        {
                            token = await client.LoginAccountMyGwmEuFrontAsync(frontRequest, cancellationToken);
                            _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=route_selected route={routeId} reason=login_success");
                            break;
                        }
                        catch (GwmApiException routeGwmException)
                        {
                            // A structured GWM response proves that this route reached the auth
                            // service. 551005/Illegal rs is even more specific: the route is valid,
                            // but the regional rs selector copied from the Brazilian client is not.
                            // Discover the EU rs value with loginAccount only; never request an SMS
                            // while probing metadata.
                            if (IsIllegalRs(routeGwmException))
                            {
                                _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=rs_discovery_start route={routeId} initial_rs={client.FrontRs} ORA_GWM_ERROR_CODE={routeGwmException.Code} message={routeGwmException.Message} sms_sent=false");
                                GwmApiException lastRsException = routeGwmException;
                                foreach (var rs in GwmApiClient.MyGwmEuFrontRsCandidates)
                                {
                                    client.UseMyGwmEuFrontProfile(options.Country, routeId, rs);
                                    _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=rs_probe route={routeId} rs={rs} endpoint=userAuth/loginAccount sms_sent=false");
                                    try
                                    {
                                        token = await client.LoginAccountMyGwmEuFrontAsync(frontRequest, cancellationToken);
                                        _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=rs_selected route={routeId} rs={rs} reason=login_success sms_sent=false");
                                        break;
                                    }
                                    catch (GwmApiException rsException)
                                    {
                                        lastRsException = rsException;
                                        if (IsIllegalRs(rsException))
                                        {
                                            _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=rs_probe_rejected route={routeId} rs={rs} ORA_GWM_ERROR_CODE={rsException.Code} message={rsException.Message} sms_sent=false");
                                            continue;
                                        }

                                        // 551008 proves that rs is accepted but the copied Brazilian
                                        // PC identity does not match the EU service. Discover the client
                                        // identity with loginAccount only; never request an SMS here.
                                        if (IsIllegalFrontIdentity(rsException))
                                        {
                                            _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=rs_selected route={routeId} rs={rs} reason=identity_error ORA_GWM_ERROR_CODE={rsException.Code} message={rsException.Message} sms_sent=false");
                                            _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_discovery_start route={routeId} rs={rs} terminal={client.FrontTerminal} brand={client.FrontBrand} enterpriseId={client.FrontEnterpriseId} sms_sent=false");

                                            GwmApiException lastIdentityException = rsException;
                                            foreach (var identity in GwmApiClient.MyGwmEuFrontIdentityCandidates)
                                            {
                                                client.UseMyGwmEuFrontIdentity(identity.Label, identity.Terminal, identity.Brand, identity.EnterpriseId);
                                                _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_probe route={routeId} rs={rs} profile={identity.Label} terminal={identity.Terminal} brand={identity.Brand} enterpriseId={identity.EnterpriseId} endpoint=userAuth/loginAccount sms_sent=false");
                                                try
                                                {
                                                    token = await client.LoginAccountMyGwmEuFrontAsync(frontRequest, cancellationToken);
                                                    _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_selected route={routeId} rs={rs} profile={identity.Label} terminal={identity.Terminal} brand={identity.Brand} enterpriseId={identity.EnterpriseId} reason=login_success sms_sent=false");
                                                    break;
                                                }
                                                catch (GwmApiException identityException)
                                                {
                                                    lastIdentityException = identityException;
                                                    if (IsIllegalFrontIdentity(identityException))
                                                    {
                                                        _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_probe_rejected route={routeId} rs={rs} profile={identity.Label} terminal={identity.Terminal} brand={identity.Brand} enterpriseId={identity.EnterpriseId} ORA_GWM_ERROR_CODE={identityException.Code} message={identityException.Message} sms_sent=false");
                                                        continue;
                                                    }

                                                    // A structured response is not automatically proof that the
                                                    // identity tuple is valid. The EU front service can return a
                                                    // generic code 001/internal-server response for an unsupported
                                                    // terminal/brand combination. Treat transient/generic backend
                                                    // failures as inconclusive and continue probing without sending SMS.
                                                    if (IsInconclusiveFrontIdentityResponse(identityException))
                                                    {
                                                        _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_probe_inconclusive route={routeId} rs={rs} profile={identity.Label} terminal={identity.Terminal} brand={identity.Brand} enterpriseId={identity.EnterpriseId} ORA_GWM_ERROR_CODE={identityException.Code} message={identityException.Message} sms_sent=false");
                                                        continue;
                                                    }

                                                    // Credential/verification-specific responses prove that the
                                                    // identity tuple reached the account flow. Preserve the selected
                                                    // headers for OTP request/redemption and let normal handling process
                                                    // the account response.
                                                    _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_selected route={routeId} rs={rs} profile={identity.Label} terminal={identity.Terminal} brand={identity.Brand} enterpriseId={identity.EnterpriseId} reason=account_response ORA_GWM_ERROR_CODE={identityException.Code} message={identityException.Message} sms_sent=false");
                                                    throw;
                                                }
                                                catch (HttpRequestException identityHttpException)
                                                {
                                                    // Some invalid front-service client identities return a plain
                                                    // HTTP 5xx instead of a structured GWM error. That must reject
                                                    // only this probe candidate, not abort the whole discovery.
                                                    _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=identity_probe_http_rejected route={routeId} rs={rs} profile={identity.Label} terminal={identity.Terminal} brand={identity.Brand} enterpriseId={identity.EnterpriseId} http_error={identityHttpException.Message} sms_sent=false");
                                                    continue;
                                                }
                                            }

                                            if (token is not null)
                                            {
                                                break;
                                            }

                                            throw lastIdentityException;
                                        }

                                        // Any other structured GWM response means the rs value is
                                        // accepted. Preserve it and hand the response to the normal
                                        // verification/credential handling below.
                                        _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=rs_selected route={routeId} rs={rs} reason=gwm_response ORA_GWM_ERROR_CODE={rsException.Code} message={rsException.Message} sms_sent=false");
                                        throw;
                                    }
                                }

                                if (token is not null)
                                {
                                    break;
                                }

                                throw lastRsException;
                            }

                            _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=route_selected route={routeId} rs={client.FrontRs} reason=gwm_response ORA_GWM_ERROR_CODE={routeGwmException.Code} message={routeGwmException.Message}");
                            throw;
                        }
                        catch (HttpRequestException routeHttpException)
                        {
                            lastRouteHttpException = routeHttpException;
                            _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=route_probe_failed route={routeId} http_error={routeHttpException.Message} sms_sent=false");
                        }
                    }
                    if (token is null)
                    {
                        throw new HttpRequestException("No MyGWM EU front-service auth route returned a usable GWM response. No verification code was requested.", lastRouteHttpException);
                    }
                }
                else if (useMyGwm13)
                {
                    _logger.LogError("ORA_AUTH_FLOW=mygwm13 ORA_AUTH_STEP=initial_login endpoint=loginAccount app=MyGWM-1.3.0");
                    token = await client.LoginAccountMyGwm13Async(new MyGwm13LoginAccountRequest
                    {
                        Account = account,
                        Password = password,
                        Country = options.Country,
                        DeviceId = options.DeviceId,
                        LoginEmail = account
                    }, cancellationToken);
                }
                else
                {
                    if (useEuVerifyCode)
                    {
                        _logger.LogError("ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=initial_login endpoint=loginAccount profile=EU_ORA");
                    }
                    token = await client.LoginAccountAsync(request, cancellationToken);
                }
                options.Account.AccessToken = token.AccessToken;
                options.Account.RefreshToken = token.RefreshToken;
                options.Account.GwId = token.GwId;
                options.Account.BeanId = token.BeanId;
                _logger.LogError($"ORA_AUTH_SUCCESS ORA_AUTH_FLOW={options.AuthFlow}");
            }
            catch (GwmApiException e) when (e.Code == "110641" || e.Code == "309702" || e.Message.Contains("verification", StringComparison.OrdinalIgnoreCase))
            {

                // SMS / mail verification login
                string code;
                if (NonInteractive)
                {
                    if (String.IsNullOrWhiteSpace(VerificationCode))
                    {
                        if (useEuMyGwmFront)
                        {
                            try
                            {
                                _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=request_code transport=eu-front-service endpoint=userAuth/getSMSCode type=3 same_device=true route={client.FrontRouteId} rs={client.FrontRs} profile={client.FrontIdentityLabel} terminal={client.FrontTerminal} brand={client.FrontBrand} enterpriseId={client.FrontEnterpriseId}");
                                await client.GetSmsCodeMyGwmEuFrontAsync(new GetSmsCode { Email = account }, cancellationToken);
                                options.AuthFlow = "eu_mygwm_front";
                                await SaveConfigAsync(options, cancellationToken);
                                throw new Exception("ORA_WAITING_FOR_CODE: My GWM EU front-service verification code requested. Please provide the received code.");
                            }
                            catch (GwmApiException frontCodeRequestException)
                            {
                                _logger.LogError($"ORA_AUTH_FRONT_REQUEST_FAILED ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=request_code ORA_GWM_ERROR_CODE={frontCodeRequestException.Code} message={frontCodeRequestException.Message}");
                                throw;
                            }
                        }

                        if (useMyGwm13)
                        {
                            try
                            {
                                _logger.LogError("ORA_AUTH_FLOW=mygwm13 ORA_AUTH_STEP=request_code endpoint=getSMSCode type=17 app=MyGWM-1.3.0");
                                await client.GetSmsCodeMyGwm13Async(new MyGwm13GetSmsCode { Email = account }, cancellationToken);
                                options.AuthFlow = "mygwm13";
                                await SaveConfigAsync(options, cancellationToken);
                                throw new Exception("ORA_WAITING_FOR_CODE: My GWM 1.3 verification code requested. Please provide the received code.");
                            }
                            catch (GwmApiException myGwmRequestException)
                            {
                                // Requesting a code is non-consuming. If GWM does not accept the
                                // newer type=17 request/profile, safely fall back to the old ORA
                                // request before any one-time code exists. Persist that choice so
                                // the following configure invocation validates the same code using
                                // the matching login flow.
                                _logger.LogError($"ORA_AUTH_FLOW=mygwm13 ORA_AUTH_STEP=request_code_failed ORA_GWM_ERROR_CODE={myGwmRequestException.Code} message={myGwmRequestException.Message}; falling_back=eu_verifycode");
                                options.AuthFlow = "eu_verifycode";
                                client.UseLegacyOraProfile();
                                await client.GetSmsCodeAsync(new GetSmsCode { Email = account }, cancellationToken);
                                await SaveConfigAsync(options, cancellationToken);
                                throw new Exception("ORA_WAITING_FOR_CODE: EU verification code requested after experimental My GWM profile was rejected. Please provide the received code.");
                            }
                        }

                        if (useEuVerifyCode)
                        {
                            _logger.LogError("ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=request_code endpoint=getSMSCode type=3 profile=EU_ORA");
                            try
                            {
                                await client.GetSmsCodeAsync(new GetSmsCode { Email = account }, cancellationToken);
                                options.AuthFlow = "eu_verifycode";
                                await SaveConfigAsync(options, cancellationToken);
                                throw new Exception("ORA_WAITING_FOR_CODE: EU verification code requested. Please provide the received code.");
                            }
                            catch (GwmApiException codeRequestException) when (
                                codeRequestException.Message.Contains("too many", StringComparison.OrdinalIgnoreCase) ||
                                codeRequestException.Message.Contains("acquired verification code", StringComparison.OrdinalIgnoreCase))
                            {
                                // My GWM 1.3 can still request a fresh verification code for the
                                // same account while the legacy EU getSMSCode/type=3 endpoint is
                                // rate-limited. Do not turn this into a fatal error: let Car2MQTT
                                // accept a code requested in the official My GWM app and continue
                                // directly with the verification/token step on the next invocation.
                                _logger.LogError($"ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=request_code_limited ORA_GWM_ERROR_CODE={codeRequestException.Code} message={codeRequestException.Message}; external_code=allowed");
                                options.AuthFlow = "eu_verifycode";
                                await SaveConfigAsync(options, cancellationToken);
                                throw new Exception("ORA_WAITING_FOR_CODE: The legacy EU code-request endpoint is rate-limited. Request one fresh verification code in the official My GWM app, do not submit it there, then enter that code in Car2MQTT.");
                            }
                        }

                        _logger.LogError("ORA_AUTH_FLOW=legacy ORA_AUTH_STEP=request_code endpoint=getSMSCode type=3 app=GWM-ORA");
                        await client.GetSmsCodeAsync(new GetSmsCode { Email = account }, cancellationToken);
                        options.AuthFlow = "legacy";
                        await SaveConfigAsync(options, cancellationToken);
                        throw new Exception("ORA_WAITING_FOR_CODE: Verification code requested. Please provide the received code.");
                    }
                    code = VerificationCode!.Trim();
                }
                else
                {
                    if (useEuMyGwmFront)
                    {
                        await client.GetSmsCodeMyGwmEuFrontAsync(new GetSmsCode { Email = account }, cancellationToken);
                    }
                    else if (useMyGwm13)
                    {
                        await client.GetSmsCodeMyGwm13Async(new MyGwm13GetSmsCode { Email = account }, cancellationToken);
                    }
                    else
                    {
                        await client.GetSmsCodeAsync(new GetSmsCode { Email = account }, cancellationToken);
                    }
                    code = Prompt.Password("Code required. Please check your mail and enter the verification code");
                }

                try
                {
                    LoginAccountResponse token;
                    if (useEuMyGwmFront)
                    {
                        // Redeem the OTP on the same front-service identity and persistent device
                        // that requested it.  Do not send it to checkSMSCode/loginWithSMS first.
                        frontRequest.VerifyCode = code;
                        _logger.LogError($"ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=verified_login transport=eu-front-service endpoint=userAuth/loginAccount verifyCode=present same_device=true route={client.FrontRouteId} rs={client.FrontRs} profile={client.FrontIdentityLabel} terminal={client.FrontTerminal} brand={client.FrontBrand} enterpriseId={client.FrontEnterpriseId}");
                        token = await client.LoginAccountMyGwmEuFrontAsync(frontRequest, cancellationToken);
                    }
                    else if (useMyGwm13)
                    {
                        // Experimental My GWM profile retained for diagnostics only.
                        _logger.LogError("ORA_AUTH_FLOW=mygwm13 ORA_AUTH_STEP=check_code endpoint=checkSMSCode type=17");
                        await client.CheckSmsCodeAsync(new CheckSmsCode
                        {
                            Email = account,
                            SmsCode = code
                        }, cancellationToken);

                        _logger.LogError("ORA_AUTH_FLOW=mygwm13 ORA_AUTH_STEP=verified_login endpoint=loginAccount verifyCode=present");
                        token = await client.LoginAccountMyGwm13Async(new MyGwm13LoginAccountRequest
                        {
                            Account = account,
                            Password = password,
                            Country = options.Country,
                            DeviceId = options.DeviceId,
                            LoginEmail = account,
                            VerifyCode = code
                        }, cancellationToken);
                    }
                    else if (useEuVerifyCode)
                    {
                        // EU hybrid: keep the exact EU identity and type=3 code request that are
                        // known to work, but avoid the loginWithSMS endpoint that returns 607198.
                        // checkSMSCode is advisory here: some regional backends do not expose it,
                        // so a failure is logged and the single final loginAccount+verifyCode call
                        // is still attempted. The OTP is never sent to two login endpoints.
                        try
                        {
                            _logger.LogError("ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=check_code endpoint=checkSMSCode type=3 profile=EU_ORA");
                            await client.CheckSmsCodeEuAsync(new EuCheckSmsCode
                            {
                                Email = account,
                                SmsCode = code
                            }, cancellationToken);
                        }
                        catch (GwmApiException checkException)
                        {
                            _logger.LogError($"ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=check_code_failed ORA_GWM_ERROR_CODE={checkException.Code} message={checkException.Message}; continuing=loginAccount_verifyCode");
                        }

                        request.VerifyCode = code;
                        _logger.LogError("ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=verified_login endpoint=loginAccount verifyCode=present profile=EU_ORA");
                        token = await client.LoginAccountAsync(request, cancellationToken);
                    }
                    else
                    {
                        var loginRequest = new LoginWithSmsRequest
                        {
                            Email = account,
                            Country = options.Country,
                            DeviceId = options.DeviceId,
                            Model = "ora2mqtt",
                            PushToken = "",
                            SmsCode = code
                        };
                        token = await client.LoginWithSmsAsync(loginRequest, cancellationToken);
                    }

                    options.Account.AccessToken = token.AccessToken;
                    options.Account.RefreshToken = token.RefreshToken;
                    options.Account.GwId = token.GwId;
                    options.Account.BeanId = token.BeanId;
                    _logger.LogError($"ORA_AUTH_SUCCESS ORA_AUTH_FLOW={options.AuthFlow}");
                }
                catch (GwmApiException verificationException)
                {
                    // Machine-readable marker consumed by Car2MQTT. Never print credentials or OTP.
                    _logger.LogError($"ORA_VERIFICATION_FAILED ORA_AUTH_FLOW={options.AuthFlow} ORA_GWM_ERROR_CODE={verificationException.Code} message={verificationException.Message}");
                    throw;
                }
            }
            catch (HttpRequestException frontHttpException) when (useEuMyGwmFront)
            {
                _logger.LogError($"ORA_AUTH_FRONT_HTTP_FAILED ORA_AUTH_FLOW=eu_mygwm_front message={frontHttpException.Message} route={client.FrontRouteId} sms_sent=false");
                throw;
            }
            catch (GwmApiException initialLoginException)
            {
                _logger.LogError($"ORA_AUTH_INITIAL_FAILED ORA_AUTH_FLOW={options.AuthFlow} ORA_GWM_ERROR_CODE={initialLoginException.Code} message={initialLoginException.Message}");
                throw;
            }
        }

        private static bool IsIllegalRs(GwmApiException exception)
        {
            return String.Equals(exception.Code, "551005", StringComparison.OrdinalIgnoreCase) ||
                exception.Message.Contains("Illegal rs", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsIllegalFrontIdentity(GwmApiException exception)
        {
            return String.Equals(exception.Code, "551008", StringComparison.OrdinalIgnoreCase) ||
                exception.Message.Contains("Illegal terminal, brand or enterpriseId", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsInconclusiveFrontIdentityResponse(GwmApiException exception)
        {
            // 001 is returned by the EU global front-service as a generic internal
            // server error for at least one unsupported client identity. It must
            // not be treated as proof that terminal/brand/enterpriseId is valid.
            return String.Equals(exception.Code, "001", StringComparison.OrdinalIgnoreCase) ||
                String.Equals(exception.Code, "607198", StringComparison.OrdinalIgnoreCase) ||
                exception.Message.Contains("internal server", StringComparison.OrdinalIgnoreCase) ||
                exception.Message.Contains("System busy", StringComparison.OrdinalIgnoreCase) ||
                exception.Message.Contains("服务器内部错误", StringComparison.OrdinalIgnoreCase);
        }

        private static string Md5Lower(string value)
        {
            var bytes = MD5.HashData(Encoding.UTF8.GetBytes(value ?? String.Empty));
            return Convert.ToHexString(bytes).ToLowerInvariant();
        }


        private void ConfigureMqttFromEnvironment(Ora2MqttOptions oraOptions)
        {
            var options = oraOptions.Mqtt;
            options.Host = Env("MQTT_HOST") ?? options.Host;
            options.Username = Env("MQTT_USERNAME") ?? options.Username;
            options.Password = Env("MQTT_PASSWORD") ?? options.Password;
            options.UseTls = String.Equals(Env("MQTT_TLS"), "true", StringComparison.OrdinalIgnoreCase);
            options.HomeAssistantDiscoveryTopic = null;
        }

        private void ConfigureMqttAsync(Ora2MqttOptions oraOptions)
        {
            var options = oraOptions.Mqtt;
            options.Host = Prompt.Input<string>("Please enter your mqtt server host or ip", defaultValue: options.Host);

            if (!Prompt.Confirm("Does your mqtt server require credentials?"))
            {
                options.Username = String.Empty;
                options.Password = String.Empty;
            }
            else
            {
                options.Username = Prompt.Input<string>("Please enter your mqtt username", defaultValue: options.Username);
                options.Password = Prompt.Password("Please enter your mqtt password");
            }

            options.UseTls = Prompt.Confirm("Do you want to use TLS on port 8883?");

            if (Prompt.Confirm("Do you want to use Home Assistant discovery?"))
            {
                options.HomeAssistantDiscoveryTopic = Prompt.Input<string>("Please enter the Home Assistant discovery topic", defaultValue: "homeassistant");
            }
            else
            {
                options.HomeAssistantDiscoveryTopic = null;
            }
        }

        private async Task<bool> TestMqttAsync(Ora2MqttOptions oraOptions, CancellationToken cancellationToken)
        {
            if (String.IsNullOrEmpty(oraOptions.Mqtt.Host)) return false;
            var options = oraOptions.Mqtt;

            try
            {
                var factory = new MqttClientFactory(new MqttLogger(LoggerFactory));
                using var client = factory.CreateMqttClient();
                var builder = new MqttClientOptionsBuilder()
                    .WithTcpServer(options.Host)
                    .WithTlsOptions(new MqttClientTlsOptions { UseTls = options.UseTls });
                if (!String.IsNullOrEmpty(options.Username) && !String.IsNullOrEmpty(options.Password))
                {
                    builder = builder.WithCredentials(options.Username, options.Password);
                }

                await client.ConnectAsync(builder.Build(), cancellationToken);
                await client.DisconnectAsync(cancellationToken: cancellationToken);
            }
            catch (MqttCommunicationException ex)
            {
                _logger.LogError($"Mqtt connection failed: {ex.Message}");
                return false;
            }
            return true;
        }
    }
}
