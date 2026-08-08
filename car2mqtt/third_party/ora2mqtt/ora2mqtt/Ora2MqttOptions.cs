namespace ora2mqtt;

public class Ora2MqttOptions
{
    public string DeviceId { get; set; }

    public string Country { get; set; }

    // "mygwm13" emulates the current My GWM 1.3 authentication path.
    // "legacy" keeps the historical GWM ORA loginWithSMS flow for rollback/debugging.
    public string AuthFlow { get; set; } = "mygwm13";

    public Ora2MqttAccountOptions Account { get; set; } = new();

    public Ora2MqttMqttOptions Mqtt { get; set; } = new();
}

public class Ora2MqttAccountOptions
{
    public string AccessToken { get; set; }

    public string RefreshToken { get; set; }

    public string GwId { get; set; }

    public string BeanId { get; set; }
}

public class Ora2MqttMqttOptions
{
    public string Host { get; set; }
    
    public string Username { get; set; }

    public string Password { get; set; }

    public bool UseTls { get; set; }

    public string HomeAssistantDiscoveryTopic { get; set; }

    public string TopicPrefixTemplate { get; set; }
}