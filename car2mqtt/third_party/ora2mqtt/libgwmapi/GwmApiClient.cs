using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace libgwmapi;

public partial class GwmApiClient
{
    public static readonly string H5HttpClientName = "eu-h5-gateway";
    public static readonly string AppHttpClientName = "eu-app-gateway";
    public static readonly string FrontHttpClientName = "eu-front-service";
    private readonly HttpClient _h5Client;
    private readonly HttpClient _appClient;
    private readonly HttpClient _frontClient;
    private readonly ILogger<GwmApiClient> _logger;

    public GwmApiClient(IHttpClientFactory factory, ILoggerFactory loggerFactory)
        : this(factory.CreateClient(H5HttpClientName), factory.CreateClient(AppHttpClientName), factory.CreateClient(FrontHttpClientName), loggerFactory)
    {
    }

    // Kept for unit tests and downstream callers that still construct the client with two transports.
    public GwmApiClient(HttpClient h5Client, HttpClient appClient, ILoggerFactory loggerFactory)
        : this(h5Client, appClient, new HttpClient(), loggerFactory)
    {
    }

    public GwmApiClient(HttpClient h5Client, HttpClient appClient, HttpClient frontClient, ILoggerFactory loggerFactory)
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
        _frontClient = frontClient;
        _appClient.DefaultRequestHeaders.Add("rs", "2");
        _appClient.DefaultRequestHeaders.Add("terminal", "GW_APP_ORA");
        _appClient.DefaultRequestHeaders.Add("brand", "3");
        _appClient.BaseAddress = new Uri("https://eu-app-gateway.gwmcloud.com/app-api/api/v1.0/");
    }

    /// <summary>
    /// Configure the dedicated My GWM EU front-service login transport.
    /// The separation is intentional: public My GWM implementations authenticate
    /// through a front-service/pc-api identity (GW_PC_GWM) and only use the app
    /// gateway after tokens have been issued.  Keeping this on a third HttpClient
    /// also prevents a My GWM OTP/challenge from being mixed with the legacy ORA
    /// H5 client identity.
    /// </summary>
    private static readonly IReadOnlyDictionary<string, string> MyGwmEuFrontRoutes =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            // The public EU app exposes eu-front-service/eu-global-service for legal/protocol
            // content.  The exact MyGWM 1.3 auth route is not publicly documented, so probe
            // only loginAccount (never getSMSCode) across plausible front-service layouts.
            ["eu_global_service_pc"] = "https://eu-front-service.gwmcloud.com/eu-global-service/pc-api/api/v1.0/",
            ["eu_global_service_official_gateway_pc"] = "https://eu-front-service.gwmcloud.com/eu-global-service/eu-official-gateway/pc-api/api/v1.0/",
            ["eu_global_service_global_gateway_pc"] = "https://eu-front-service.gwmcloud.com/eu-global-service/eu-global-gateway/pc-api/api/v1.0/",
            ["eu_official_gateway_pc"] = "https://eu-front-service.gwmcloud.com/eu-official-gateway/pc-api/api/v1.0/",
            ["eu_official_commerce_official_gateway_pc"] = "https://eu-front-service.gwmcloud.com/eu-official-commerce/eu-official-gateway/pc-api/api/v1.0/",
        };

    public static IReadOnlyList<string> MyGwmEuFrontRouteIds { get; } = MyGwmEuFrontRoutes.Keys.ToArray();

    // rs is a region/service selector used by GWM. Public Brazilian MyGWM clients
    // use rs=5 on their PC/front-service login route, but the EU global gateway
    // rejects that value with GWM code 551005 (Illegal rs). Probe only loginAccount
    // with these values before any SMS request is allowed.
    public static IReadOnlyList<string> MyGwmEuFrontRsCandidates { get; } =
        new[] { "2", "1", "3", "4", "0", "6", "7", "8", "9" };

    // Known GWM client identities from public implementations.  The EU front-service
    // route accepted rs=2 but rejected the Brazilian PC identity with 551008. Probe
    // these identities using loginAccount only; no SMS is requested during discovery.
    public static IReadOnlyList<(string Label, string Terminal, string Brand, string EnterpriseId)> MyGwmEuFrontIdentityCandidates { get; } =
        new (string Label, string Terminal, string Brand, string EnterpriseId)[]
        {
            ("mygwm_app", "GW_APP_GWM", "6", "CC01"),
            ("legacy_ora", "GW_APP_ORA", "3", "CC01"),
            ("haval_app", "GW_APP_Haval", "1", "CC01"),
            ("haval_app_upper", "GW_APP_HAVAL", "1", "CC01"),
            ("pc_gwm_brand3", "GW_PC_GWM", "3", "CC01"),
            ("pc_gwm_brand1", "GW_PC_GWM", "1", "CC01"),
        };

    public string FrontRouteId { get; private set; } = String.Empty;
    public string FrontRs { get; private set; } = "5";
    public string FrontIdentityLabel { get; private set; } = "pc_gwm";
    public string FrontTerminal { get; private set; } = "GW_PC_GWM";
    public string FrontBrand { get; private set; } = "6";
    public string FrontEnterpriseId { get; private set; } = "CC01";

    public void UseMyGwmEuFrontProfile(string country, string routeId = "eu_global_service_pc", string rs = "5")
    {
        if (!MyGwmEuFrontRoutes.TryGetValue(routeId, out _))
        {
            throw new ArgumentException($"Unknown MyGWM EU front route: {routeId}", nameof(routeId));
        }
        FrontRouteId = routeId;
        FrontRs = rs;
        SetHeader(_frontClient, "appid", "6");
        SetHeader(_frontClient, "brandid", "CCZ001");
        SetHeader(_frontClient, "country", country);
        SetHeader(_frontClient, "devicetype", "0");
        _frontClient.DefaultRequestHeaders.Remove("gwid");
        _frontClient.DefaultRequestHeaders.TryAddWithoutValidation("gwid", String.Empty);
        SetHeader(_frontClient, "language", CountryToFrontLanguage(country));
        SetHeader(_frontClient, "rs", rs);
        UseMyGwmEuFrontIdentity("pc_gwm", "GW_PC_GWM", "6", "CC01");
    }

    public void UseMyGwmEuFrontIdentity(string label, string terminal, string brand, string enterpriseId)
    {
        FrontIdentityLabel = label;
        FrontTerminal = terminal;
        FrontBrand = brand;
        FrontEnterpriseId = enterpriseId;
        SetHeader(_frontClient, "terminal", terminal);
        SetHeader(_frontClient, "brand", brand);
        SetHeader(_frontClient, "enterpriseid", enterpriseId);
    }

    private static string CountryToFrontLanguage(string country)
    {
        return (country ?? String.Empty).Trim().ToUpperInvariant() switch
        {
            "DE" => "de_DE",
            "GB" => "en_GB",
            "SE" => "sv_SE",
            "IT" => "it_IT",
            "ES" => "es_ES",
            _ => "en_US"
        };
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
            _frontClient.DefaultRequestHeaders.Remove("country");
            _frontClient.DefaultRequestHeaders.Add("country", value);
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
        _frontClient.DefaultRequestHeaders.Remove("accessToken");
        _frontClient.DefaultRequestHeaders.Add("accessToken", accessToken);
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

    private Uri GetFrontUri(string url)
    {
        var routeId = String.IsNullOrWhiteSpace(FrontRouteId) ? MyGwmEuFrontRouteIds[0] : FrontRouteId;
        if (!MyGwmEuFrontRoutes.TryGetValue(routeId, out var baseUrl))
        {
            throw new InvalidOperationException($"Unknown MyGWM EU front route: {routeId}");
        }

        return new Uri(new Uri(baseUrl), url);
    }

    private async Task PostFrontAsync<T>(string url, T body, CancellationToken cancellationToken)
    {
        var response = await _frontClient.PostAsJsonAsync(GetFrontUri(url), body, cancellationToken);
        await CheckResponseAsync(response, cancellationToken);
    }

    private async Task<TOut> PostFrontAsync<TIn, TOut>(string url, TIn body, CancellationToken cancellationToken)
    {
        var response = await _frontClient.PostAsJsonAsync(GetFrontUri(url), body, cancellationToken);
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
        await ReadGwmResponseAsync<GwmResponse>(response, cancellationToken);
    }

    private async Task<T> GetResponseAsync<T>(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var result = await ReadGwmResponseAsync<GwmResponse<T>>(response, cancellationToken);
        return result.Data;
    }

    private async Task<T> ReadGwmResponseAsync<T>(HttpResponseMessage response, CancellationToken cancellationToken)
        where T : GwmResponse
    {
        // GWM sometimes returns a useful JSON error body together with HTTP 4xx/5xx.
        // Parse that body before EnsureSuccessStatusCode so callers get the actual
        // GWM code (for example 551008) instead of losing it behind HttpRequestException.
        var content = await response.Content.ReadAsStringAsync(cancellationToken);
        if (_logger.IsEnabled(LogLevel.Trace))
        {
            _logger.LogTrace(content);
        }

        T result;
        try
        {
            result = JsonSerializer.Deserialize<T>(content);
        }
        catch (JsonException) when (!response.IsSuccessStatusCode)
        {
            response.EnsureSuccessStatusCode();
            throw;
        }

        if (result is null)
        {
            response.EnsureSuccessStatusCode();
            throw new JsonException("GWM response body was empty.");
        }

        CheckResponse(result);
        response.EnsureSuccessStatusCode();
        return result;
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