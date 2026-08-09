using libgwmapi.DTO.User;
using libgwmapi.DTO.UserAuth;

namespace libgwmapi;

public partial class GwmApiClient
{
    public Task<CustomerServicePhone> GetCustomerServicePhoneAsync(string countryCode, CancellationToken cancellationToken)
    {
        return GetH5Async<CustomerServicePhone>($"userAuth/customerServicePhone?countryCode={countryCode}",
            cancellationToken);
    }

    public Task GetSmsCodeAsync(GetSmsCode request, CancellationToken cancellationToken)
    {
        return PostH5Async("userAuth/getSMSCode", request, cancellationToken);
    }

    public Task<LoginAccountResponse> LoginWithSmsAsync(LoginWithSmsRequest request, CancellationToken cancellationToken)
    {
        return PostH5Async<LoginWithSmsRequest, LoginAccountResponse>("userAuth/loginWithSMS", request, cancellationToken);
    }

    public Task<LoginAccountResponse> LoginAccountAsync(LoginAccountRequest request, CancellationToken cancellationToken)
    {
        return PostH5Async<LoginAccountRequest, LoginAccountResponse>("userAuth/loginAccount", request, cancellationToken);
    }

    public Task GetSmsCodeMyGwm13Async(MyGwm13GetSmsCode request, CancellationToken cancellationToken)
    {
        return PostH5Async("userAuth/getSMSCode", request, cancellationToken);
    }

    public Task CheckSmsCodeAsync(CheckSmsCode request, CancellationToken cancellationToken)
    {
        return PostH5Async("userAuth/checkSMSCode", request, cancellationToken);
    }

    public Task CheckSmsCodeEuAsync(EuCheckSmsCode request, CancellationToken cancellationToken)
    {
        return PostH5Async("userAuth/checkSMSCode", request, cancellationToken);
    }

    public Task<LoginAccountResponse> LoginAccountMyGwm13Async(MyGwm13LoginAccountRequest request, CancellationToken cancellationToken)
    {
        return PostH5Async<MyGwm13LoginAccountRequest, LoginAccountResponse>("userAuth/loginAccount", request, cancellationToken);
    }

    public Task<LoginAccountResponse> LoginAccountMyGwmEuFrontAsync(MyGwmEuFrontLoginRequest request, CancellationToken cancellationToken)
    {
        return PostFrontAsync<MyGwmEuFrontLoginRequest, LoginAccountResponse>("userAuth/loginAccount", request, cancellationToken);
    }

    public Task<LoginAccountResponse> LoginAccountMyGwmEuFrontAppAsync(LoginAccountRequest request, CancellationToken cancellationToken)
    {
        return PostFrontAsync<LoginAccountRequest, LoginAccountResponse>("userAuth/loginAccount", request, cancellationToken);
    }

    // EU verification flow: redeem the one-time code via loginWithSMS on the
    // same MyGWM front-service app-api route/headers/device that requested it.
    public Task<LoginAccountResponse> LoginWithSmsMyGwmEuFrontAppAsync(LoginWithSmsRequest request, CancellationToken cancellationToken)
    {
        return PostFrontAsync<LoginWithSmsRequest, LoginAccountResponse>("userAuth/loginWithSMS", request, cancellationToken);
    }

    public Task<LoginAccountResponse> LoginAccountMyGwmEuFrontApp13Async(MyGwm13LoginAccountRequest request, CancellationToken cancellationToken)
    {
        return PostFrontAsync<MyGwm13LoginAccountRequest, LoginAccountResponse>("userAuth/loginAccount", request, cancellationToken);
    }

    public Task GetSmsCodeMyGwmEuFrontApp13Async(MyGwm13GetSmsCode request, CancellationToken cancellationToken)
    {
        return PostFrontAsync("userAuth/getSMSCode", request, cancellationToken);
    }

    public Task GetSmsCodeMyGwmEuFrontAsync(GetSmsCode request, CancellationToken cancellationToken)
    {
        return PostFrontAsync("userAuth/getSMSCode", request, cancellationToken);
    }

    public Task CheckSecurityPasswordAsync(CheckSecurityPassword request, CancellationToken cancellationToken)
    {
        return PostH5Async("userAuth/checkSecurityPassword", request, cancellationToken);
    }

    public Task AddAppDeviceInfoAsync(AddAppDevice request, CancellationToken cancellationToken)
    {
        return PostH5Async("userAuth/addAppDeviceInfo", request, cancellationToken);
    }

    public Task<RefreshTokenResponse> RefreshTokenAsync(RefreshTokenRequest request, CancellationToken cancellationToken)
    {
        return PostH5Async<RefreshTokenRequest, RefreshTokenResponse>("userAuth/refreshToken", request, cancellationToken);
    }
}