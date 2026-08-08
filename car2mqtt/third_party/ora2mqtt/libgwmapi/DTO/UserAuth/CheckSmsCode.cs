using System.Text.Json.Serialization;

namespace libgwmapi.DTO.UserAuth;

public class CheckSmsCode
{
    [JsonPropertyName("email")]
    public string Email { get; set; }

    [JsonPropertyName("smsCode")]
    public string SmsCode { get; set; }

    [JsonPropertyName("type")]
    public string Type { get; set; } = "17";
}
