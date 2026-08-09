using System.Globalization;
using System.Text.Json;
using System.Text;
using CommandLine;
using libgwmapi;
using MQTTnet;
using YamlDotNet.Serialization;
using libgwmapi.DTO.UserAuth;
using libgwmapi.DTO.Vehicle;
using Microsoft.Extensions.Logging;
using ora2mqtt.Logging;

namespace ora2mqtt;

[Verb("run", true, HelpText = "default")]
public class RunCommand:BaseCommand
{
    private ILogger _logger;

    [Option('i', "interval", Default = 10, HelpText = "GWM API polling interval")]
    public int Intervall { get; set; }

    public async Task<int> Run(CancellationToken cancellationToken)
    {
        Setup();
        _logger = LoggerFactory.CreateLogger<RunCommand>();
        if (!File.Exists(ConfigFile))
        {
            _logger.LogError($"config file ({ConfigFile}) missing");
            return 1;
        }
        Ora2MqttOptions config;
        var deserializer = new Deserializer();
        using (var file = File.OpenText(ConfigFile))
        {
            config = deserializer.Deserialize<Ora2MqttOptions>(file);
        }

        var api = GetGwmApiClient(config);
        using var mqtt = await ConnectMqttAsync(config.Mqtt, api, cancellationToken);

        var publishHaDiscovery = config.Mqtt.HomeAssistantDiscoveryTopic is not null;

        try
        {
            using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Intervall));
            while (!cancellationToken.IsCancellationRequested)
            {
                await RefreshTokenAsync(api, config, cancellationToken);
                try
                {
                    await PublishStatusAsync(mqtt, api, config.Mqtt, publishHaDiscovery, cancellationToken);
                }
                catch (GwmApiException runtimeAuthException) when
                    (String.Equals(config.AuthFlow, "eu_mygwm_front", StringComparison.OrdinalIgnoreCase) &&
                     IsRuntimeAuthError(runtimeAuthException))
                {
                    _logger.LogWarning($"MyGWM runtime token rejected (GWM code={runtimeAuthException.Code}; {runtimeAuthException.Message}). Refreshing on the same front-service app-api context...");
                    await RefreshTokenAsync(api, config, cancellationToken, force: true);
                    await PublishStatusAsync(mqtt, api, config.Mqtt, publishHaDiscovery, cancellationToken);
                }
                if (publishHaDiscovery)
                {
                    publishHaDiscovery = false;
                }
                await timer.WaitForNextTickAsync(cancellationToken);
            }
        }
        catch (TaskCanceledException)
        {
            //ignore
        }
        return 0;
    }

    private async Task<IMqttClient> ConnectMqttAsync(Ora2MqttMqttOptions options, GwmApiClient api, CancellationToken cancellationToken)
    {
        var factory = new MqttClientFactory(new MqttLogger(LoggerFactory));
        var client = factory.CreateMqttClient();
        var builder = new MqttClientOptionsBuilder()
            .WithTcpServer(options.Host)
            .WithTlsOptions(new MqttClientTlsOptions { UseTls = options.UseTls });
        if (!String.IsNullOrEmpty(options.Username) && !String.IsNullOrEmpty(options.Password))
        {
            builder = builder.WithCredentials(options.Username, options.Password);
        }

        client.DisconnectedAsync += async e =>
        {
            if (e.ClientWasConnected)
            {
                await client.ConnectAsync(client.Options, cancellationToken);
            }
        };

        await client.ConnectAsync(builder.Build(), cancellationToken);
        if (options.HomeAssistantDiscoveryTopic is not null)
        {
            client.ApplicationMessageReceivedAsync += x => OnMessageAsync(x, client, api, options, cancellationToken);
            await client.SubscribeAsync($"{options.HomeAssistantDiscoveryTopic}/status", cancellationToken: cancellationToken);
        }
        return client;
    }

    private Task OnMessageAsync(MqttApplicationMessageReceivedEventArgs arg, IMqttClient mqtt, GwmApiClient api, Ora2MqttMqttOptions options, CancellationToken cancellationToken)
    {
        if (arg.ApplicationMessage.Topic == $"{options.HomeAssistantDiscoveryTopic}/status")
        {
            return PublishStatusAsync(mqtt, api, options, true, cancellationToken);
        }
        return Task.CompletedTask;
    }

    private GwmApiClient GetGwmApiClient(Ora2MqttOptions options)
    {
        var client = ConfigureApiClient(options);
        if (String.Equals(options.AuthFlow, "eu_mygwm_front", StringComparison.OrdinalIgnoreCase))
        {
            // Authentication succeeded on the MyGWM EU front-service app-api lane.
            // Vehicle data itself follows the normal regional app gateway, but with
            // the MyGWM vehicle identity rather than the discontinued ORA identity.
            client.UseMyGwmEuFrontProfile(options.Country, "eu_global_service_global_gateway_app", "2");
            client.UseMyGwmEuFrontIdentity("mygwm13_app", "GW_APP_GWM", "6", "CC01");
            client.UseMyGwmEuRuntimeProfile(options.Country);
            _logger.LogInformation("ORA runtime profile: MyGWM EU app-api (GW_APP_GWM, brand=6, rs=2)");
        }
        client.SetAccessToken(options.Account.AccessToken);
        client.SetRefreshToken(options.Account.RefreshToken);
        return client;
    }

    private async Task RefreshTokenAsync(GwmApiClient client, Ora2MqttOptions options, CancellationToken cancellationToken, bool force = false)
    {
        var useMyGwmFront = String.Equals(options.AuthFlow, "eu_mygwm_front", StringComparison.OrdinalIgnoreCase);
        if (useMyGwmFront)
        {
            // Do not validate a freshly issued MyGWM token through the legacy ORA H5
            // user endpoint. That cross-profile check returns 607501 even though the
            // token was just issued successfully. Only refresh when the JWT itself is
            // near expiry, or when a real runtime API call rejected it.
            if (!force && !IsJwtExpiredOrNearExpiry(options.Account.AccessToken))
            {
                return;
            }
            _logger.LogInformation("Refreshing MyGWM EU access token on front-service app-api...");
        }
        else
        {
            try
            {
                // Legacy ORA token validation.
                await client.GetUserBaseInfoAsync(cancellationToken);
                return;
            }
            catch (GwmApiException e)
            {
                _logger.LogError($"Access token expired ({e.Message}). Trying to refresh token...");
            }
        }

        var refresh = new RefreshTokenRequest
        {
            DeviceId = options.DeviceId,
            AccessToken = options.Account.AccessToken,
            RefreshToken = options.Account.RefreshToken,
        };

        if (!useMyGwmFront)
        {
            _logger.LogInformation("Refreshing ORA access token...");
        }
        client.SetAccessToken("");

        var refreshTask = useMyGwmFront
            ? client.RefreshTokenMyGwmEuFrontAsync(refresh, cancellationToken)
            : client.RefreshTokenAsync(refresh, cancellationToken);
        var completed = await Task.WhenAny(refreshTask, Task.Delay(TimeSpan.FromSeconds(30), cancellationToken));
        if (completed != refreshTask)
        {
            _logger.LogError("ORA token refresh timed out after 30 seconds.");
            throw new TimeoutException("ORA token refresh timed out after 30 seconds.");
        }

        try
        {
            var response = await refreshTask;
            options.Account.AccessToken = response.AccessToken;
            options.Account.RefreshToken = response.RefreshToken;
            await SaveConfigAsync(options, cancellationToken);
            client.SetAccessToken(options.Account.AccessToken);
            client.SetRefreshToken(options.Account.RefreshToken);
            _logger.LogInformation(useMyGwmFront ? "MyGWM EU token refresh successful." : "ORA token refresh successful.");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "ORA token refresh failed.");
            throw;
        }
    }

    private static bool IsRuntimeAuthError(GwmApiException exception)
    {
        var message = exception.Message ?? String.Empty;
        return exception.Code == "607501" ||
               exception.Code == "110641" ||
               message.Contains("token", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("logged in elsewhere", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("login again", StringComparison.OrdinalIgnoreCase);
    }

    private static bool IsJwtExpiredOrNearExpiry(string accessToken)
    {
        if (String.IsNullOrWhiteSpace(accessToken))
        {
            return true;
        }
        try
        {
            var parts = accessToken.Split('.');
            if (parts.Length < 2)
            {
                // Some GWM deployments use opaque tokens. Do not force-refresh an
                // opaque token merely because its expiry cannot be decoded.
                return false;
            }
            var payload = parts[1].Replace('-', '+').Replace('_', '/');
            payload += payload.Length % 4 switch
            {
                2 => "==",
                3 => "=",
                _ => String.Empty
            };
            var json = Encoding.UTF8.GetString(Convert.FromBase64String(payload));
            using var document = JsonDocument.Parse(json);
            if (!document.RootElement.TryGetProperty("exp", out var expElement) ||
                !expElement.TryGetInt64(out var exp))
            {
                return false;
            }
            return DateTimeOffset.UtcNow >= DateTimeOffset.FromUnixTimeSeconds(exp).AddMinutes(-1);
        }
        catch
        {
            return false;
        }
    }

    private async Task PublishStatusAsync(IMqttClient mqtt, GwmApiClient gwm, Ora2MqttMqttOptions options, bool publishHaDiscovery, CancellationToken cancellationToken)
    {
        var vehicles = await gwm.AcquireVehiclesAsync(cancellationToken);
        foreach (var vehicle in vehicles)
        {
            var status = await gwm.GetLastVehicleStatusAsync(vehicle.Vin, cancellationToken);
            var topicPrefix = GetTopicPrefix(options, vehicle.Vin);
            if (publishHaDiscovery)
            {
                await PublishHaDiscoveryAsync(mqtt, options, vehicle, status, cancellationToken);
            }
            await PublishMessageAsync(mqtt, $"{topicPrefix}/AcquisitionTime", status.AcquisitionTime, cancellationToken);
            await PublishMessageAsync(mqtt, $"{topicPrefix}/UpdateTime", status.UpdateTime, cancellationToken);
            if (status.Latitude.HasValue && status.Longitude.HasValue)
            {
                await PublishMessageAsync(mqtt, $"{topicPrefix}/Latitude", status.Latitude.Value, cancellationToken);
                await PublishMessageAsync(mqtt, $"{topicPrefix}/Longitude", status.Longitude.Value, cancellationToken);
                await PublishMessageAsync(mqtt, $"{topicPrefix}/Location", JsonSerializer.Serialize(new
                {
                    latitude = status.Latitude.Value,
                    longitude = status.Longitude.Value
                }), cancellationToken);
            }

            foreach (var item in status.Items)
            {
                if (item.Value is null) continue;
                await PublishMessageAsync(mqtt, $"{topicPrefix}/items/{item.Code}/value", item.Value.ToString(), cancellationToken);
                if (item.Unit is not null)
                    await PublishMessageAsync(mqtt, $"{topicPrefix}/items/{item.Code}/unit", item.Unit, cancellationToken);
            }
        }
    }


    private static string GetTopicPrefix(Ora2MqttMqttOptions options, string vin)
    {
        var template = options.TopicPrefixTemplate;
        if (String.IsNullOrWhiteSpace(template))
        {
            return $"GWM/{vin}/status";
        }

        return template.Replace("{vin}", vin).Replace("{VIN}", vin).Trim('/');
    }

    private Task PublishHaDiscoveryAsync(IMqttClient mqtt, Ora2MqttMqttOptions options, Vehicle vehicle, VehicleStatus status, CancellationToken cancellationToken)
    {
        var topicPrefix = GetTopicPrefix(options, vehicle.Vin);
        var json = JsonSerializer.Serialize(new
        {
            dev = new
            {
                ids = vehicle.Vin,
                name = vehicle.AppShowSeriesName,
                mf = vehicle.BrandName,
                mdl = vehicle.Vtype,
                sn = status.DeviceId
            },
            o = new
            {
                name = "ora2mqtt",
                url = "https://github.com/zivillian/ora2mqtt"
            },
            cmps = new
            {
                location = new
                {
                    p="device_tracker",
                    icon="mdi:map-marker",
                    json_attributes_topic=$"{topicPrefix}/Location",
                    unique_id=$"gwm_{vehicle.Vin}_location",
                    name="Location"
                },
                acquisition=new
                {
                    p = "sensor",
                    device_class = "timestamp",
                    unique_id = $"gwm_{vehicle.Vin}_AcquisitionTime",
                    state_topic = $"{topicPrefix}/AcquisitionTime",
                    name = "Acquisition",
                    value_template = "{{ (value|int // 1000) | timestamp_utc }}"
                },
                status_2013021 = new
                {
                    p="sensor",
                    device_class = "battery",
                    unique_id= $"gwm_{vehicle.Vin}_2013021",
                    unit_of_measurement="%",
                    state_topic= $"{topicPrefix}/items/2013021/value",
                    state_class= "measurement",
                    name="SOC"
                },
                status_2011501 = new
                {
                    p="sensor",
                    device_class = "distance",
                    unique_id = $"gwm_{vehicle.Vin}_2011501",
                    unit_of_measurement ="km",
                    state_topic = $"{topicPrefix}/items/2011501/value",
                    state_class = "measurement",
                    name="Range"
                },
                status_2041301 = new
                {
                    p="sensor",
                    unique_id = $"gwm_{vehicle.Vin}_2041301",
                    unit_of_measurement ="%",
                    state_topic = $"{topicPrefix}/items/2041301/value",
                    state_class = "measurement",
                    name="SOCE",
                    icon= "mdi:battery-heart-variant"
                },
                status_2101001 = new
                {
                    p="sensor",
                    device_class = "pressure",
                    unique_id = $"gwm_{vehicle.Vin}_2101001",
                    unit_of_measurement ="kPa",
                    state_topic = $"{topicPrefix}/items/2101001/value",
                    state_class = "measurement",
                    name="Tire Pressure FL",
                    icon= "mdi:car-tire-alert"
                },
                status_2101002 = new
                {
                    p="sensor",
                    device_class = "pressure",
                    unique_id = $"gwm_{vehicle.Vin}_2101002",
                    unit_of_measurement ="kPa",
                    state_topic = $"{topicPrefix}/items/2101002/value",
                    state_class = "measurement",
                    name="Tire Pressure FR",
                    icon= "mdi:car-tire-alert"
                },
                status_2101003 = new
                {
                    p="sensor",
                    device_class = "pressure",
                    unique_id = $"gwm_{vehicle.Vin}_2101003",
                    unit_of_measurement ="kPa",
                    state_topic = $"{topicPrefix}/items/2101003/value",
                    state_class = "measurement",
                    name="Tire Pressure RL",
                    icon= "mdi:car-tire-alert"
                },
                status_2101004 = new
                {
                    p="sensor",
                    device_class = "pressure",
                    unique_id = $"gwm_{vehicle.Vin}_2101004",
                    unit_of_measurement ="kPa",
                    state_topic = $"{topicPrefix}/items/2101004/value",
                    state_class = "measurement",
                    name="Tire Pressure RR",
                    icon= "mdi:car-tire-alert"
                },
                status_2101005 = new
                {
                    p="sensor",
                    device_class = "temperature",
                    unique_id = $"gwm_{vehicle.Vin}_2101005",
                    unit_of_measurement ="°C",
                    state_topic = $"{topicPrefix}/items/2101005/value",
                    state_class = "measurement",
                    name="Tire Temperature FL"
                },
                status_2101006 = new
                {
                    p="sensor",
                    device_class = "temperature",
                    unique_id = $"gwm_{vehicle.Vin}_2101006",
                    unit_of_measurement ="°C",
                    state_topic = $"{topicPrefix}/items/2101006/value",
                    state_class = "measurement",
                    name="Tire Temperature FR"
                },
                status_2101007 = new
                {
                    p="sensor",
                    device_class = "temperature",
                    unique_id = $"gwm_{vehicle.Vin}_2101007",
                    unit_of_measurement ="°C",
                    state_topic = $"{topicPrefix}/items/2101007/value",
                    state_class = "measurement",
                    name="Tire Temperature RL"
                },
                status_2101008 = new
                {
                    p="sensor",
                    device_class = "temperature",
                    unique_id = $"gwm_{vehicle.Vin}_2101008",
                    unit_of_measurement ="°C",
                    state_topic = $"{topicPrefix}/items/2101008/value",
                    state_class = "measurement",
                    name="Tire Temperature RR"
                },
                status_2103010 = new
                {
                    p = "sensor",
                    device_class = "distance",
                    unique_id = $"gwm_{vehicle.Vin}_2103010",
                    unit_of_measurement = "km",
                    state_topic = $"{topicPrefix}/items/2103010/value",
                    state_class = "measurement",
                    name = "Odometer",
                    icon="mdi:counter"
                },
                status_2201001 = new
                {
                    p = "sensor",
                    device_class = "temperature",
                    unique_id = $"gwm_{vehicle.Vin}_2201001",
                    unit_of_measurement = "°C",
                    state_topic = $"{topicPrefix}/items/2201001/value",
                    state_class = "measurement",
                    name = "Interior Temperature",
                    value_template = "{{ value|int / 10 }}"
                },
                status_2202001 = new
                {
                    p = "binary_sensor",
                    unique_id = $"gwm_{vehicle.Vin}_2202001",
                    state_topic = $"{topicPrefix}/items/2202001/value",
                    name = "A/C",
                    payload_off = "0",
                    payload_on = "1",
                    icon= "mdi:air-conditioner"
                },
                status_2208001 = new
                {
                    p = "binary_sensor",
                    device_class = "lock",
                    unique_id = $"gwm_{vehicle.Vin}_2208001",
                    state_topic = $"{topicPrefix}/items/2208001/value",
                    name = "Lock",
                    payload_off = "0",
                    payload_on = "1"
                },
                status_2210001 = new
                {
                    p = "binary_sensor",
                    device_class = "window",
                    unique_id = $"gwm_{vehicle.Vin}_2210001",
                    state_topic = $"{topicPrefix}/items/2210001/value",
                    name = "Window FL",
                    payload_off = "1",
                    payload_on = "3"
                },
                status_2210002 = new
                {
                    p = "binary_sensor",
                    device_class = "window",
                    unique_id = $"gwm_{vehicle.Vin}_2210002",
                    state_topic = $"{topicPrefix}/items/2210002/value",
                    name = "Window FR",
                    payload_off = "1",
                    payload_on = "3"
                },
                status_2210003 = new
                {
                    p = "binary_sensor",
                    device_class = "window",
                    unique_id = $"gwm_{vehicle.Vin}_2210003",
                    state_topic = $"{topicPrefix}/items/2210003/value",
                    name = "Window RL",
                    payload_off = "1",
                    payload_on = "3"
                },
                status_2210004 = new
                {
                    p = "binary_sensor",
                    device_class = "window",
                    unique_id = $"gwm_{vehicle.Vin}_2210004",
                    state_topic = $"{topicPrefix}/items/2210004/value",
                    name = "Window RR",
                    payload_off = "1",
                    payload_on = "3"
                },
                status_2078020 = new
                {
                    p = "binary_sensor",
                    device_class = "running",
                    unique_id = $"gwm_{vehicle.Vin}_2078020",
                    state_topic = $"{topicPrefix}/items/2078020/value",
                    name = "Air Circulation",
                    payload_off = "0",
                    payload_on = "1"
                },
                status_2222001 = new
                {
                    p = "binary_sensor",
                    unique_id = $"gwm_{vehicle.Vin}_2222001",
                    state_topic = $"{topicPrefix}/items/2222001/value",
                    name = "Front defroster",
                    payload_off = "0",
                    payload_on = "1",
                    icon= "mdi:car-defrost-front"
                },
                status_2042082 = new
                {
                    p = "binary_sensor",
                    device_class= "plug",
                    unique_id = $"gwm_{vehicle.Vin}_2042082",
                    state_topic = $"{topicPrefix}/items/2042082/value",
                    name = "Charge plug",
                    payload_off = "0",
                    payload_on = "1",
                },
            }
        });
        return PublishMessageAsync(mqtt, $"{options.HomeAssistantDiscoveryTopic}/device/{vehicle.Vin}/config", json, cancellationToken);
    }

    private Task PublishMessageAsync(IMqttClient client, string topic, double payload, CancellationToken cancellationToken)
    {
        return PublishMessageAsync(client, topic, payload.ToString(CultureInfo.InvariantCulture), cancellationToken);
    }

    private Task PublishMessageAsync(IMqttClient client, string topic, long payload, CancellationToken cancellationToken)
    {
        return PublishMessageAsync(client, topic, payload.ToString(CultureInfo.InvariantCulture), cancellationToken);
    }

    private Task PublishMessageAsync(IMqttClient client, string topic, string payload, CancellationToken cancellationToken)
    {
        var message = new MqttApplicationMessageBuilder()
            .WithTopic(topic)
            .WithPayload(payload)
            .Build();
        return client.PublishAsync(message, cancellationToken);
    }
}