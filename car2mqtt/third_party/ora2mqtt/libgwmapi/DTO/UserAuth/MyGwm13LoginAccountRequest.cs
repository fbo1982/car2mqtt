using System.Text.Json.Serialization;

namespace libgwmapi.DTO.UserAuth;

/// <summary>
/// Candidate My GWM 1.3 loginAccount body based on GWM's newer app login flow.
/// The OTP is carried as verifyCode after checkSMSCode, instead of calling the
/// legacy ORA loginWithSMS endpoint.
/// </summary>
public class MyGwm13LoginAccountRequest
{
    [JsonPropertyName("account")]
    public string Account { get; set; }

    [JsonPropertyName("password")]
    public string Password { get; set; }

    [JsonPropertyName("agreement")]
    public int[] Agreement { get; set; } = { 1, 2 };

    [JsonPropertyName("deviceId")]
    public string DeviceId { get; set; }

    [JsonPropertyName("appType")]
    public string AppType { get; set; } = "0";

    [JsonPropertyName("country")]
    public string Country { get; set; }

    [JsonPropertyName("accountId")]
    public string AccountId { get; set; }

    [JsonPropertyName("uid")]
    public string Uid { get; set; }

    [JsonPropertyName("smsCode")]
    public string SmsCode { get; set; }

    [JsonPropertyName("pushToken")]
    public string PushToken { get; set; } = String.Empty;

    [JsonPropertyName("loginEmail")]
    public string LoginEmail { get; set; }

    [JsonPropertyName("verifyCode")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string VerifyCode { get; set; }
}
