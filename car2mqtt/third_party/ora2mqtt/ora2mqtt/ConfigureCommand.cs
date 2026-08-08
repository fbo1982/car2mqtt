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
            (Env("ORA_AUTH_FLOW") ?? options.AuthFlow ?? "eu_verifycode").Trim().ToLowerInvariant();

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
            var useMyGwm13 = String.Equals(authFlow, "mygwm13", StringComparison.OrdinalIgnoreCase);
            var useEuVerifyCode = String.Equals(authFlow, "eu_verifycode", StringComparison.OrdinalIgnoreCase);
            options.AuthFlow = useMyGwm13 ? "mygwm13" : (useEuVerifyCode ? "eu_verifycode" : "legacy");
            if (useMyGwm13)
            {
                // Experimental only: v1.2.38 showed EU rejecting this identity before OTP request.
                client.UseMyGwm13Profile();
            }
            else
            {
                // EU hybrid and legacy both use the proven EU ORA client identity.
                client.UseLegacyOraProfile();
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
            try
            {
                LoginAccountResponse token;
                if (useMyGwm13)
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
                    if (useMyGwm13)
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
                    if (useMyGwm13)
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
            catch (GwmApiException initialLoginException)
            {
                _logger.LogError($"ORA_AUTH_INITIAL_FAILED ORA_AUTH_FLOW={options.AuthFlow} ORA_GWM_ERROR_CODE={initialLoginException.Code} message={initialLoginException.Message}");
                throw;
            }
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
