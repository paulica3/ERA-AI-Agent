using System.Text;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddRazorPages();
builder.Services.AddHttpClient();

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error");
    app.UseHsts();
}


app.UseHttpsRedirection();
app.UseRouting();
app.UseAuthorization();

// ── Auth gate ─────────────────────────────────────────────────────────────────
// User-facing pages require a logged-in session (the httpOnly era_jwt cookie).
// Unauthenticated GETs to a protected page redirect to /LogIn. The API proxies
// enforce auth themselves (Python returns 401), so they are not gated here.
var protectedPages = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
{
    "/", "/index", "/dashboard", "/account", "/settings"
};
app.Use(async (ctx, next) =>
{
    var path = ctx.Request.Path.Value ?? "/";
    if (HttpMethods.IsGet(ctx.Request.Method)
        && protectedPages.Contains(path)
        && !ctx.Request.Cookies.ContainsKey("era_jwt"))
    {
        ctx.Response.Redirect("/LogIn");
        return;
    }
    await next();
});

app.MapStaticAssets();
app.MapRazorPages().WithStaticAssets();

var jsonOptions = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
};

app.MapPost("/api/title", async (TitleRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    // Always return a usable title — never a Problem response.
    // If anything fails, fall back to a truncated version of the user's message.
    var fallback = req.Message is { Length: > 0 }
        ? req.Message[..Math.Min(35, req.Message.Length)]
        : "Conversație nouă";

    try
    {
        var apiKey = config["AnthropicApiKey"];
        if (string.IsNullOrEmpty(apiKey)) return Results.Ok(new { title = fallback });

        var httpClient = factory.CreateClient();
        httpClient.DefaultRequestHeaders.Add("x-api-key", apiKey);
        httpClient.DefaultRequestHeaders.Add("anthropic-version", "2023-06-01");

        var context = string.IsNullOrWhiteSpace(req.Reply)
            ? req.Message
            : $"User: {req.Message}\nAssistant: {req.Reply[..Math.Min(300, req.Reply.Length)]}";

        var requestBody = new AnthropicRequest(
            Model: "claude-sonnet-4-20250514",
            MaxTokens: 20,
            System: "Generezi titluri ultra-scurte pentru conversații în limba română. Răspunde doar cu 2-3 cuvinte — fără punctuație, fără ghilimele, fără explicații.",
            Messages: [new ChatMessage("user", $"Rezumă această conversație într-un titlu de 2-3 cuvinte în română:\n{context}")]
        );

        var content = JsonContent.Create(requestBody, options: jsonOptions);
        var response = await httpClient.PostAsync("https://api.anthropic.com/v1/messages", content);
        if (!response.IsSuccessStatusCode) return Results.Ok(new { title = fallback });

        var result = await response.Content.ReadFromJsonAsync<AnthropicResponse>(jsonOptions);
        var title = result?.Content?.FirstOrDefault()?.Text?.Trim() ?? fallback;
        return Results.Ok(new { title });
    }
    catch
    {
        return Results.Ok(new { title = fallback });
    }
});

// Chat now runs server-side in Python: it loads the per-user profile, injects it,
// calls Claude (with web search), persists messages, and writes the audit snapshot.
// This proxy just forwards the JWT (from the httpOnly cookie) as a Bearer token.
app.MapPost("/api/chat", async (JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
{
    var pythonApiUrl = config["PythonApiUrl"];
    if (string.IsNullOrEmpty(pythonApiUrl))
        return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

    var httpClient = PythonClient(factory, config, ctx, timeoutSec: 220);
    var content = new StringContent(body.GetRawText(), Encoding.UTF8, "application/json");
    try
    {
        var resp = await httpClient.PostAsync($"{pythonApiUrl}/chat", content);
        var respBody = await resp.Content.ReadAsStringAsync();
        return Results.Content(respBody, "application/json", Encoding.UTF8, (int)resp.StatusCode);
    }
    catch (TaskCanceledException)
    {
        return Results.Json(new { error = "Răspunsul a durat prea mult." }, statusCode: 504);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapPost("/api/analyze", async (HttpRequest httpReq, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
{
    var pythonApiUrl = config["PythonApiUrl"];
    if (string.IsNullOrEmpty(pythonApiUrl))
    {
        ctx.Response.StatusCode = 500;
        ctx.Response.ContentType = "application/json";
        await ctx.Response.WriteAsync("{\"error\":\"Python API URL nu este configurat.\"}");
        return;
    }

    if (!httpReq.HasFormContentType)
    {
        ctx.Response.StatusCode = 400;
        ctx.Response.ContentType = "application/json";
        await ctx.Response.WriteAsync("{\"error\":\"Expected multipart/form-data.\"}");
        return;
    }

    var form = await httpReq.ReadFormAsync();
    var file = form.Files.GetFile("file");
    if (file is null)
    {
        ctx.Response.StatusCode = 400;
        ctx.Response.ContentType = "application/json";
        await ctx.Response.WriteAsync("{\"error\":\"Niciun fișier încărcat.\"}");
        return;
    }

    using var ms = new MemoryStream();
    await file.CopyToAsync(ms);
    ms.Seek(0, SeekOrigin.Begin);

    var httpClient = factory.CreateClient();
    httpClient.Timeout = TimeSpan.FromSeconds(220);

    var eraApiKey = config["EraApiKey"];
    if (!string.IsNullOrEmpty(eraApiKey))
        httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

    using var formContent = new MultipartFormDataContent();
    using var fileContent = new StreamContent(ms);
    fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
        file.ContentType ?? "application/octet-stream");
    formContent.Add(fileContent, "file", file.FileName ?? "document");

    HttpResponseMessage upstreamResp;
    try
    {
        upstreamResp = await httpClient.SendAsync(
            new HttpRequestMessage(HttpMethod.Post, $"{pythonApiUrl}/analyze") { Content = formContent },
            HttpCompletionOption.ResponseHeadersRead);
    }
    catch (TaskCanceledException)
    {
        ctx.Response.StatusCode = 504;
        ctx.Response.ContentType = "application/json";
        await ctx.Response.WriteAsync("{\"error\":\"Analiza a durat prea mult. Documentul este probabil prea lung.\"}");
        return;
    }
    catch (Exception ex)
    {
        ctx.Response.StatusCode = 500;
        ctx.Response.ContentType = "application/json";
        await ctx.Response.WriteAsync($"{{\"error\":\"Eroare internă: {ex.Message}\"}}");
        return;
    }

    if (!upstreamResp.IsSuccessStatusCode)
    {
        var err = await upstreamResp.Content.ReadAsStringAsync();
        ctx.Response.StatusCode = 502;
        ctx.Response.ContentType = "application/json";
        await ctx.Response.WriteAsync($"{{\"error\":\"Python API ({(int)upstreamResp.StatusCode}): {err}\"}}");
        return;
    }

    ctx.Response.ContentType = "text/event-stream";
    ctx.Response.Headers["Cache-Control"] = "no-cache";
    ctx.Response.Headers["X-Accel-Buffering"] = "no";

    await using var stream = await upstreamResp.Content.ReadAsStreamAsync();
    using var reader = new System.IO.StreamReader(stream);

    while (!reader.EndOfStream && !ctx.RequestAborted.IsCancellationRequested)
    {
        var line = await reader.ReadLineAsync();
        if (line is null) break;
        await ctx.Response.WriteAsync(line + "\n");
        if (line == string.Empty)
            await ctx.Response.Body.FlushAsync();
    }
});

app.MapPost("/api/draft-invoice", async (DraftInvoiceRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(60);

        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        var content = JsonContent.Create(req, options: jsonOptions);
        var resp = await httpClient.PostAsync($"{pythonApiUrl}/draft-invoice", content);

        if (!resp.IsSuccessStatusCode)
        {
            var err = await resp.Content.ReadAsStringAsync();
            return Results.Json(new { error = $"Python API ({(int)resp.StatusCode}): {err}" }, statusCode: 502);
        }

        var bytes = await resp.Content.ReadAsByteArrayAsync();
        var safeName = (req.CompanyName ?? "document").Replace(" ", "_").Replace("/", "_");
        safeName = safeName[..Math.Min(30, safeName.Length)];
        return Results.File(bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", $"Invoice_{safeName}.docx");
    }
    catch (TaskCanceledException)
    {
        return Results.Json(new { error = "Cererea a durat prea mult." }, statusCode: 504);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapPost("/api/draft-contract", async (DraftContractRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(220);

        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        var content = JsonContent.Create(req, options: jsonOptions);
        var resp = await httpClient.PostAsync($"{pythonApiUrl}/draft-contract", content);

        if (!resp.IsSuccessStatusCode)
        {
            var err = await resp.Content.ReadAsStringAsync();
            return Results.Json(new { error = $"Python API ({(int)resp.StatusCode}): {err}" }, statusCode: 502);
        }

        var bytes = await resp.Content.ReadAsByteArrayAsync();
        var safeName = (req.ClientName ?? "document").Replace(" ", "_").Replace("/", "_");
        safeName = safeName[..Math.Min(30, safeName.Length)];
        var filename = $"Contract_{safeName}.docx";
        return Results.File(bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename);
    }
    catch (TaskCanceledException)
    {
        return Results.Json(
            new { error = "Redactarea a durat prea mult. Documentul este probabil prea complex." },
            statusCode: 504);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapPost("/api/generate-custom-offer", async (GenerateOfferRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

        var httpClient = factory.CreateClient();
        // PDF export runs LibreOffice; allow generous time.
        httpClient.Timeout = TimeSpan.FromSeconds(220);

        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        var content = JsonContent.Create(req, options: jsonOptions);
        var resp = await httpClient.PostAsync($"{pythonApiUrl}/generate-custom-offer", content);

        if (!resp.IsSuccessStatusCode)
        {
            var err = await resp.Content.ReadAsStringAsync();
            return Results.Json(new { error = $"Python API ({(int)resp.StatusCode}): {err}" }, statusCode: 502);
        }

        var bytes = await resp.Content.ReadAsByteArrayAsync();
        var safeName = (req.ClientName ?? "Oferta").Replace(" ", "_").Replace("/", "_");
        safeName = safeName[..Math.Min(30, safeName.Length)];

        var isPdf = string.Equals(req.Format, "pdf", StringComparison.OrdinalIgnoreCase);
        var mime = isPdf
            ? "application/pdf"
            : "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        var ext = isPdf ? "pdf" : "pptx";
        return Results.File(bytes, mime, $"Oferta_{safeName}.{ext}");
    }
    catch (TaskCanceledException)
    {
        return Results.Json(new { error = "Generarea ofertei a durat prea mult." }, statusCode: 504);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapPost("/api/generate-general-description", async (GenerateGeneralDescriptionRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

        var httpClient = factory.CreateClient();
        // PDF export runs LibreOffice; allow generous time.
        httpClient.Timeout = TimeSpan.FromSeconds(220);

        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        var content = JsonContent.Create(req, options: jsonOptions);
        var resp = await httpClient.PostAsync($"{pythonApiUrl}/generate-general-description", content);

        if (!resp.IsSuccessStatusCode)
        {
            var err = await resp.Content.ReadAsStringAsync();
            return Results.Json(new { error = $"Python API ({(int)resp.StatusCode}): {err}" }, statusCode: 502);
        }

        var bytes = await resp.Content.ReadAsByteArrayAsync();
        var isPdf = string.Equals(req.Format, "pdf", StringComparison.OrdinalIgnoreCase);
        var mime = isPdf
            ? "application/pdf"
            : "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        var ext = isPdf ? "pdf" : "pptx";
        return Results.File(bytes, mime, $"Prezentare_ERA.{ext}");
    }
    catch (TaskCanceledException)
    {
        return Results.Json(new { error = "Generarea prezentării a durat prea mult." }, statusCode: 504);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

// ── Track-record dashboard (projects store) ──────────────────────────────────
app.MapGet("/api/projects", async (IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);
        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(30);
        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);
        var resp = await httpClient.GetAsync($"{pythonApiUrl}/projects");
        var body = await resp.Content.ReadAsStringAsync();
        return Results.Content(body, "application/json", Encoding.UTF8, (int)resp.StatusCode);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapPut("/api/projects", async (JsonElement body, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);
        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(30);
        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);
        var content = new StringContent(body.GetRawText(), Encoding.UTF8, "application/json");
        var resp = await httpClient.PutAsync($"{pythonApiUrl}/projects", content);
        var respBody = await resp.Content.ReadAsStringAsync();
        return Results.Content(respBody, "application/json", Encoding.UTF8, (int)resp.StatusCode);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapPost("/api/translate", async (JsonElement body, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);
        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(60);
        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);
        var content = new StringContent(body.GetRawText(), Encoding.UTF8, "application/json");
        var resp = await httpClient.PostAsync($"{pythonApiUrl}/translate", content);
        var respBody = await resp.Content.ReadAsStringAsync();
        return Results.Content(respBody, "application/json", Encoding.UTF8, (int)resp.StatusCode);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

app.MapGet("/api/chat-instructions", async (IConfiguration config, IHttpClientFactory factory) =>
{
    var instructions = await FetchInstructions(config, factory);
    return Results.Ok(new { instructions });
});

app.MapPut("/api/chat-instructions", async (ChatInstructions body, IConfiguration config, IHttpClientFactory factory) =>
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(15);

        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        var content = JsonContent.Create(body, options: jsonOptions);
        var resp = await httpClient.PutAsync($"{pythonApiUrl}/chat-instructions", content);
        if (!resp.IsSuccessStatusCode)
        {
            var err = await resp.Content.ReadAsStringAsync();
            return Results.Json(new { error = $"Python API ({(int)resp.StatusCode}): {err}" }, statusCode: 502);
        }

        var data = await resp.Content.ReadFromJsonAsync<ChatInstructions>();
        return Results.Ok(new { instructions = data?.Instructions ?? "" });
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
});

// ══════════════════════════════════════════════════════════════════════════════
// Adaptive learning: auth (cookie handoff), conversations, profile, account.
//
// The browser never sees the JWT. On login/register the C# proxy stores the
// token Python returns in an httpOnly Secure SameSite=Lax cookie (era_jwt), and
// forwards it as Authorization: Bearer on every user-facing Python call.
// ══════════════════════════════════════════════════════════════════════════════

app.MapPost("/api/auth/login", async (JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await AuthProxy("/auth/login", body, config, factory, ctx));

app.MapPost("/api/auth/register", async (JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await AuthProxy("/auth/register", body, config, factory, ctx));

app.MapPost("/api/auth/logout", (HttpContext ctx) =>
{
    ClearAuthCookie(ctx);
    return Results.Ok(new { ok = true });
});

// ── Conversations (JWT, ownership-scoped in Python) ───────────────────────────
app.MapGet("/api/conversations", async (IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Get, "/conversations", null, config, factory, ctx));

app.MapPost("/api/conversations", async (JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Post, "/conversations", body, config, factory, ctx));

app.MapGet("/api/conversations/{id:int}", async (int id, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Get, $"/conversations/{id}", null, config, factory, ctx));

app.MapMethods("/api/conversations/{id:int}", new[] { "PATCH" }, async (int id, JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Patch, $"/conversations/{id}", body, config, factory, ctx));

app.MapDelete("/api/conversations/{id:int}", async (int id, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Delete, $"/conversations/{id}", null, config, factory, ctx));

// ── Profile (JWT) ─────────────────────────────────────────────────────────────
app.MapGet("/api/profile", async (IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Get, "/profile", null, config, factory, ctx));

app.MapPut("/api/profile", async (JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Put, "/profile", body, config, factory, ctx));

// ── Suggestions (Phase 2) ─────────────────────────────────────────────────────
app.MapGet("/api/suggestions", async (IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Get, "/suggestions", null, config, factory, ctx));

app.MapMethods("/api/suggestions/{id}", ["PATCH"], async (int id, JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
    await ForwardJson(HttpMethod.Patch, $"/suggestions/{id}", body, config, factory, ctx));

// ── Account: GDPR wipe (JWT). Clears the session cookie on success. ───────────
app.MapDelete("/api/account", async (IConfiguration config, IHttpClientFactory factory, HttpContext ctx) =>
{
    var result = await ForwardJson(HttpMethod.Delete, "/account", null, config, factory, ctx);
    ClearAuthCookie(ctx);
    return result;
});

// ── Helpers ────────────────────────────────────────────────────────────────────

// Build an HttpClient for Python calls: always sends x-era-api-key, and forwards
// the era_jwt cookie as a Bearer token when present.
static HttpClient PythonClient(IHttpClientFactory factory, IConfiguration config, HttpContext ctx, int timeoutSec = 60)
{
    var client = factory.CreateClient();
    client.Timeout = TimeSpan.FromSeconds(timeoutSec);
    var eraApiKey = config["EraApiKey"];
    if (!string.IsNullOrEmpty(eraApiKey))
        client.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);
    if (ctx.Request.Cookies.TryGetValue("era_jwt", out var token) && !string.IsNullOrEmpty(token))
        client.DefaultRequestHeaders.Authorization =
            new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);
    return client;
}

static void SetAuthCookie(HttpContext ctx, string token) =>
    ctx.Response.Cookies.Append("era_jwt", token, new CookieOptions
    {
        HttpOnly = true,
        Secure = true,
        SameSite = SameSiteMode.Lax,
        Path = "/",
        MaxAge = TimeSpan.FromDays(7),
    });

static void ClearAuthCookie(HttpContext ctx) =>
    ctx.Response.Cookies.Delete("era_jwt", new CookieOptions
    {
        HttpOnly = true,
        Secure = true,
        SameSite = SameSiteMode.Lax,
        Path = "/",
    });

// Proxy a login/register call: on success, stash the JWT in the cookie and
// return the rest of the body (display_name, email) to the browser.
static async Task<IResult> AuthProxy(string path, JsonElement body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx)
{
    var pythonApiUrl = config["PythonApiUrl"];
    if (string.IsNullOrEmpty(pythonApiUrl))
        return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

    var client = factory.CreateClient();
    client.Timeout = TimeSpan.FromSeconds(30);
    var eraApiKey = config["EraApiKey"];
    if (!string.IsNullOrEmpty(eraApiKey))
        client.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

    try
    {
        var content = new StringContent(body.GetRawText(), Encoding.UTF8, "application/json");
        var resp = await client.PostAsync($"{pythonApiUrl}{path}", content);
        var respBody = await resp.Content.ReadAsStringAsync();
        if (!resp.IsSuccessStatusCode)
            return Results.Content(respBody, "application/json", Encoding.UTF8, (int)resp.StatusCode);

        using var doc = JsonDocument.Parse(respBody);
        var root = doc.RootElement;
        if (root.TryGetProperty("access_token", out var tok) && tok.GetString() is { Length: > 0 } token)
            SetAuthCookie(ctx, token);

        var displayName = root.TryGetProperty("display_name", out var dn) ? dn.GetString() : "";
        var email = root.TryGetProperty("email", out var em) ? em.GetString() : "";
        return Results.Ok(new { display_name = displayName, email });
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
}

// Forward a JSON request to Python with the JWT cookie attached, relaying the
// status code and body verbatim.
static async Task<IResult> ForwardJson(HttpMethod method, string path, JsonElement? body, IConfiguration config, IHttpClientFactory factory, HttpContext ctx)
{
    var pythonApiUrl = config["PythonApiUrl"];
    if (string.IsNullOrEmpty(pythonApiUrl))
        return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

    var client = PythonClient(factory, config, ctx);
    var request = new HttpRequestMessage(method, $"{pythonApiUrl}{path}");
    if (body is { } b)
        request.Content = new StringContent(b.GetRawText(), Encoding.UTF8, "application/json");

    try
    {
        var resp = await client.SendAsync(request);
        var respBody = await resp.Content.ReadAsStringAsync();
        return Results.Content(respBody, "application/json", Encoding.UTF8, (int)resp.StatusCode);
    }
    catch (Exception ex)
    {
        return Results.Json(new { error = $"Eroare internă: {ex.Message}" }, statusCode: 500);
    }
}

// Fetch the user's standing instructions from the Python service (best-effort).
static async Task<string> FetchInstructions(IConfiguration config, IHttpClientFactory factory)
{
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl)) return "";

        var httpClient = factory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(10);

        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        var resp = await httpClient.GetAsync($"{pythonApiUrl}/chat-instructions");
        if (!resp.IsSuccessStatusCode) return "";

        var data = await resp.Content.ReadFromJsonAsync<ChatInstructions>();
        return data?.Instructions ?? "";
    }
    catch
    {
        return "";
    }
}

app.Run();

record ChatInstructions(string? Instructions);
record TitleRequest(string Message, string? Reply = null);
record ChatMessage(string Role, string Content);
record AnthropicTool(string Type, string Name);
record AnthropicRequest(string Model, int MaxTokens, string System, List<ChatMessage> Messages, List<AnthropicTool>? Tools = null, bool? Stream = null);
record AnthropicResponse(List<AnthropicContent> Content);
record AnthropicContent(string Type, string? Text);
record DraftInvoiceRequest(
    string Date,
    string CompanyName,
    string? LegalAddress,
    string? ClientIban,
    string? RegNo,
    string? VatNo,
    string? InvoiceNumber,
    string? ContractRef,
    string? ServiceDescription,
    string? LegalFee,
    string? Currency,
    string? ExpensesText,
    string? PartnerName,
    string? PartnerTitle,
    string? PartnerEmail
);

record DraftContractRequest(
    string ClientName,
    string? ClientType,
    string? ClientIdno,
    string? ClientAddress,
    string? ClientRep,
    string? ClientRepRole,
    string Scope,
    string? Services,
    string? Fees,
    string? Duration,
    string? ContractNumber
);

record GenerateOfferRequest(
    string ClientName,
    string Date,
    string AddresseeSalutation,
    string? AddresseeBlock,
    string? IntroText,
    bool ComposeIntro,
    string? FeeText,
    string? SignatoryName,
    string? SignatoryTitle,
    string? Lang,
    bool ReformatFees,
    string? Format
);

record GenerateGeneralDescriptionRequest(
    string AddresseeBlock,
    string AddresseeSalutation,
    string? Date,
    string? IntroContext,
    bool ComposeIntro,
    string? SignatoryName,
    string? SignatoryTitle,
    string? HourlyRate,
    string? Lang,
    string? Format
);
