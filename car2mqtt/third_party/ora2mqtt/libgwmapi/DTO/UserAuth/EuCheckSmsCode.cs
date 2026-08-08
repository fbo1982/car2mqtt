using System.Text.Json.Serialization;

namespace libgwmapi.DTO.UserAuth;

/// <summary>
/// EU verification-code check matching the legacy EU getSMSCode request (type=3).
/// </summary>
public class EuCheckSmsCode
{
    [JsonPropertyName("email")]
    public string Email { get; set; }

    [JsonPropertyName("smsCode")]
    public string SmsCode { get; set; }

    [JsonPropertyName("type")]
    public int Type { get; set; } = 3;
}
