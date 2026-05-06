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
app.MapStaticAssets();
app.MapRazorPages().WithStaticAssets();

const string SystemPrompt =
    "Ești un asistent juridic AI pentru firma de avocatură Efrim Roșca & Asociații " +
    "din Republica Moldova. Ești profesionist, concis și precis, cu terminologie juridică precisă. " +
    "Detectează automat limba în care scrie utilizatorul și răspunde în aceeași limbă. " +
    "Limba implicită este română — dacă nu poți detecta limba, răspunde în română. " +
    "Indiferent de limbă, menții același nivel de profesionalism și precizie juridică.";

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
            System: "You generate ultra-short chat titles. Reply with 2-3 words only — no punctuation, no quotes, no explanation.",
            Messages: [new ChatMessage("user", $"Summarize this conversation as a 2-3 word title:\n{context}")]
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

app.MapPost("/api/chat", async (ChatRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    var apiKey = config["AnthropicApiKey"];
    if (string.IsNullOrEmpty(apiKey))
        return Results.Problem("Cheia API nu este configurată.");

    var httpClient = factory.CreateClient();
    httpClient.DefaultRequestHeaders.Add("x-api-key", apiKey);
    httpClient.DefaultRequestHeaders.Add("anthropic-version", "2023-06-01");
    httpClient.DefaultRequestHeaders.Add("anthropic-beta", "web-search-2025-03-05");

    var requestBody = new AnthropicRequest(
        Model: "claude-sonnet-4-20250514",
        MaxTokens: 4096,
        System: SystemPrompt,
        Messages: req.Messages,
        Tools: [new AnthropicTool("web_search_20250305", "web_search")]
    );

    var content = JsonContent.Create(requestBody, options: jsonOptions);
    var response = await httpClient.PostAsync("https://api.anthropic.com/v1/messages", content);

    if (!response.IsSuccessStatusCode)
        return Results.Problem("Eroare de la serviciul AI.");

    var result = await response.Content.ReadFromJsonAsync<AnthropicResponse>(jsonOptions);
    // Only return text blocks — web search result blocks are handled server-side by Claude
    var reply = string.Join("\n", result?.Content?
        .Where(c => c.Type == "text" && c.Text != null)
        .Select(c => c.Text!) ?? []);
    return Results.Ok(new { reply = string.IsNullOrWhiteSpace(reply) ? "Eroare de răspuns." : reply });
});

app.MapPost("/api/analyze", async (HttpRequest httpReq, IConfiguration config, IHttpClientFactory factory) =>
{
    // Always return JSON — never let an exception escape and produce an HTML error page.
    try
    {
        var pythonApiUrl = config["PythonApiUrl"];
        if (string.IsNullOrEmpty(pythonApiUrl))
            return Results.Json(new { error = "Python API URL nu este configurat." }, statusCode: 500);

        if (!httpReq.HasFormContentType)
            return Results.Json(new { error = "Expected multipart/form-data." }, statusCode: 400);

        var form = await httpReq.ReadFormAsync();
        var file = form.Files.GetFile("file");
        if (file is null) return Results.Json(new { error = "Niciun fișier încărcat." }, statusCode: 400);

        // Forward the file to the Python API unchanged
        using var ms = new MemoryStream();
        await file.CopyToAsync(ms);
        ms.Seek(0, SeekOrigin.Begin);

        var httpClient = factory.CreateClient();
        // Azure App Service caps inbound requests at ~230s — stay just below that
        // so we time out cleanly on our side rather than Azure dropping the connection.
        httpClient.Timeout = TimeSpan.FromSeconds(220);

        // Shared secret so the Python API only accepts requests from this .NET app
        var eraApiKey = config["EraApiKey"];
        if (!string.IsNullOrEmpty(eraApiKey))
            httpClient.DefaultRequestHeaders.Add("x-era-api-key", eraApiKey);

        using var formContent = new MultipartFormDataContent();
        using var fileContent = new StreamContent(ms);
        fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
            file.ContentType ?? "application/octet-stream");
        formContent.Add(fileContent, "file", file.FileName ?? "document");

        var resp = await httpClient.PostAsync($"{pythonApiUrl}/analyze", formContent);

        if (!resp.IsSuccessStatusCode)
        {
            var err = await resp.Content.ReadAsStringAsync();
            return Results.Json(new { error = $"Python API ({(int)resp.StatusCode}): {err}" }, statusCode: 502);
        }

        // Stream the JSON response back to the browser as-is
        var json = await resp.Content.ReadAsStringAsync();
        return Results.Content(json, "application/json");
    }
    catch (TaskCanceledException)
    {
        return Results.Json(
            new { error = "Analiza a durat prea mult. Documentul este probabil prea lung." },
            statusCode: 504);
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

app.Run();

record TitleRequest(string Message, string? Reply = null);
record ChatRequest(List<ChatMessage> Messages);
record ChatMessage(string Role, string Content);
record AnthropicTool(string Type, string Name);
record AnthropicRequest(string Model, int MaxTokens, string System, List<ChatMessage> Messages, List<AnthropicTool>? Tools = null);
record AnthropicResponse(List<AnthropicContent> Content);
record AnthropicContent(string Type, string? Text);
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
