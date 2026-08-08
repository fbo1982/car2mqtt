using System.Text.Json.Serialization;

namespace libgwmapi.DTO.UserAuth;

/// <summary>
/// My GWM front-service login body.  Public My GWM clients use the lower-case
/// deviceid field and an MD5 password on the PC/front-service login endpoint.
/// verifyCode is only included on the post-OTP login attempt.
/// </summary>
public class MyGwmEuFrontLoginRequest
{
    [JsonPropertyName("account")]
    public string Account { get; set; }

    [JsonPropertyName("password")]
    public string Password { get; set; }

    [JsonPropertyName("deviceid")]
    public string DeviceId { get; set; }

    [JsonPropertyName("verifyCode")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string VerifyCode { get; set; }
}
