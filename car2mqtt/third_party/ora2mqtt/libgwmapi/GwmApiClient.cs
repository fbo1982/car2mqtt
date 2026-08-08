using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace libgwmapi;

public partial class GwmApiClient
{
    public static readonly string H5HttpClientName = "eu-h5-gateway";
    public static readonly string AppHttpClientName = "eu-app-gateway";
    private readonly HttpClient _h5Client;
    private readonly HttpClient _appClient;
    private readonly ILogger<GwmApiClient> _logger;

    public GwmApiClient(IHttpClientFactory factory, ILoggerFactory loggerFactory)
        : this(factory.CreateClient(H5HttpClientName), factory.CreateClient(AppHttpClientName), loggerFactory)
    {
    }

    public GwmApiClient(HttpClient h5Client, HttpClient appClient, ILoggerFactory loggerFactory)
    {
        _logger = loggerFactory.CreateLogger<GwmApiClient>();
        _h5Client = h5Client;
        _h5Client.DefaultRequestHeaders.Add("rs", "2");
        _h5Client.DefaultRequestHeaders.Add("terminal", "GW_APP_ORA");
        _h5Client.DefaultRequestHeaders.Add("brand", "3");
        _h5Client.DefaultRequestHeaders.Add("language", "en");
        _h5Client.DefaultRequestHeaders.Add("systemType", "1");
        _h5Client.DefaultRequestHeaders.Add("cver", "");
        _h5Client.BaseAddress = new Uri("https://eu-h5-gateway.gwmcloud.com/app-api/api/v1.0/");
        
        _appClient = appClient;
        _appClient.DefaultRequestHeaders.Add("rs", "2");
        _appClient.DefaultRequestHeaders.Add("terminal", "GW_APP_ORA");
        _appClient.DefaultRequestHeaders.Add("brand", "3");
        _appClient.BaseAddress = new Uri("https://eu-app-gateway.gwmcloud.com/app-api/api/v1.0/");
    }

    /// <summary>
    /// Switch request identity from the discontinued ORA app profile to the
    /// current My GWM application profile.  Vehicle/API endpoints stay on the
    /// EU GWM gateways; only the client identity headers are changed.
    /// </summary>
    public void UseMyGwm13Profile()
    {
        foreach (var client in new[] { _h5Client, _appClient })
        {
            SetHeader(client, "terminal", "GW_APP_GWM");
            SetHeader(client, "brand", "6");
            SetHeader(client, "enterpriseId", "CC01");
            SetHeader(client, "appId", "1");
            SetHeader(client, "channel", "APP");
            SetHeader(client, "cver", "1.3.0");
            SetHeader(client, "systemType", "1");
        }
    }

    public void UseLegacyOraProfile()
    {
        foreach (var client in new[] { _h5Client, _appClient })
        {
            SetHeader(client, "terminal", "GW_APP_ORA");
            SetHeader(client, "brand", "3");
            client.DefaultRequestHeaders.Remove("enterpriseId");
            client.DefaultRequestHeaders.Remove("appId");
            client.DefaultRequestHeaders.Remove("channel");
        }
        SetHeader(_h5Client, "cver", String.Empty);
        SetHeader(_h5Client, "systemType", "1");
        _appClient.DefaultRequestHeaders.Remove("cver");
        _appClient.DefaultRequestHeaders.Remove("systemType");
    }

    private static void SetHeader(HttpClient client, string name, string value)
    {
        client.DefaultRequestHeaders.Remove(name);
        client.DefaultRequestHeaders.Add(name, value);
    }

    public string Language
    {
        get => _h5Client.DefaultRequestHeaders.GetValues("language").FirstOrDefault();
        set
        {
            _h5Client.DefaultRequestHeaders.Remove("language");
            _h5Client.DefaultRequestHeaders.Add("language", value);
        }
    }

    public string Country
    {
        get => _h5Client.DefaultRequestHeaders.GetValues("country").FirstOrDefault();
        set
        {
            _h5Client.DefaultRequestHeaders.Remove("country");
            _h5Client.DefaultRequestHeaders.Add("country", value);
            _appClient.DefaultRequestHeaders.Remove("country");
            _appClient.DefaultRequestHeaders.Add("country", value);
        }
    }

    public bool HasAccessToken
    {
        get
        {
            if (!_h5Client.DefaultRequestHeaders.TryGetValues("accessToken", out var token))
                return false;
            return token.Any(x => !String.IsNullOrEmpty(x));
        }
    }

    public void SetAccessToken(string accessToken)
    {
        _h5Client.DefaultRequestHeaders.Remove("accessToken");
        _h5Client.DefaultRequestHeaders.Add("accessToken", accessToken);

        _appClient.DefaultRequestHeaders.Remove("accessToken");
        _appClient.DefaultRequestHeaders.Add("accessToken", accessToken);
    }

    private async Task PostH5Async<T>(string url, T body, CancellationToken cancellationToken)
    {
        var response = await _h5Client.PostAsJsonAsync(url, body, cancellationToken);
        await CheckResponseAsync(response, cancellationToken);
    }

    private async Task PostAppAsync<T>(string url, T body, CancellationToken cancellationToken)
    {
        var response = await _appClient.PostAsJsonAsync(url, body, cancellationToken);
        await CheckResponseAsync(response, cancellationToken);
    }

    private async Task<TOut> PostH5Async<TIn, TOut>(string url, TIn body, CancellationToken cancellationToken)
    {
        var response = await _h5Client.PostAsJsonAsync(url, body, cancellationToken);
        return await GetResponseAsync<TOut>(response, cancellationToken);
    }

    private async Task<T> GetH5Async<T>(string url, CancellationToken cancellationToken)
    {
        var response = await _h5Client.GetAsync(url, cancellationToken);
        return await GetResponseAsync<T>(response, cancellationToken);
    }

    private async Task<T> GetAppAsync<T>(string url, CancellationToken cancellationToken)
    {
        var response = await _appClient.GetAsync(url, cancellationToken);
        return await GetResponseAsync<T>(response, cancellationToken);
    }

    private async Task CheckResponseAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (_logger.IsEnabled(LogLevel.Trace))
        {
            await response.Content.LoadIntoBufferAsync();
            _logger.LogTrace(await response.Content.ReadAsStringAsync(cancellationToken));
        }
        response.EnsureSuccessStatusCode();
        var result = await response.Content.ReadFromJsonAsync<GwmResponse>(cancellationToken: cancellationToken);
        CheckResponse(result);
    }

    private async Task<T> GetResponseAsync<T>(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (_logger.IsEnabled(LogLevel.Trace))
        {
            await response.Content.LoadIntoBufferAsync();
            _logger.LogTrace(await response.Content.ReadAsStringAsync(cancellationToken));
        }
        response.EnsureSuccessStatusCode();
        var result = await response.Content.ReadFromJsonAsync<GwmResponse<T>>(cancellationToken: cancellationToken);
        CheckResponse(result);
        return result.Data;
    }

    private void CheckResponse(GwmResponse response)
    {
        if (response.Code != "000000")
        {
            throw new GwmApiException(response.Code, response.Description);
        }
    }

    private class GwmResponse
    {
        [JsonPropertyName("code")]
        public string Code { get; set; }

        [JsonPropertyName("description")]
        public string Description { get; set; }
    }

    private class GwmResponse<T>:GwmResponse
    {

        [JsonPropertyName("data")]
        public T Data { get; set; }
    }

    private class GwmArrayResponse<T>:GwmResponse
    {

        [JsonPropertyName("data")]
        public T[] Data { get; set; }
    }
}