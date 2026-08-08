using System.Text.Json.Serialization;

namespace libgwmapi.DTO.UserAuth;

/// <summary>
/// Login verification code request used by the newer My GWM style flow.
/// The type="17" login-verification scenario is also used by GWM's newer
/// regional app flow, instead of the legacy EU ORA type=3 request.
/// </summary>
public class MyGwm13GetSmsCode
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "17";

    [JsonPropertyName("email")]
    public string Email { get; set; }

    [JsonPropertyName("accountId")]
    public string AccountId { get; set; }

    [JsonPropertyName("uid")]
    public string Uid { get; set; }
}
