using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddRazorPages();
builder.Services.AddHttpClient();

// ── Python API auto-start ────────────────────────────────────────────────────
// Locate the uvicorn executable inside the Python virtual environment.
// Path is relative to this project file, going up one level to reach /PY.
var pyRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "PY"));

// Windows: .venv/Scripts/uvicorn.exe  |  Mac/Linux: .venv/bin/uvicorn
var uvicorn = RuntimeInformation.IsOSPlatform(OSPlatform.Windows)
    ? Path.Combine(pyRoot, ".venv", "Scripts", "uvicorn.exe")
    : Path.Combine(pyRoot, ".venv", "bin", "uvicorn");

Process? pythonProcess = null;

if (File.Exists(uvicorn))
{
    pythonProcess = new Process
    {
        StartInfo = new ProcessStartInfo
        {
            FileName         = uvicorn,
            Arguments        = "api:app --port 8000 --reload",
            WorkingDirectory = pyRoot,
            UseShellExecute  = false,   // run silently, no extra window
            CreateNoWindow   = true,
        }
    };
    pythonProcess.Start();
    Console.WriteLine("✓ Python API server started on http://localhost:8000");
}
else
{
    Console.WriteLine($"⚠ uvicorn not found at: {uvicorn}");
    Console.WriteLine("  Run: cd PY && .venv/bin/pip install uvicorn  (Mac/Linux)");
    Console.WriteLine("  Run: cd PY && .venv\\Scripts\\pip install uvicorn  (Windows)");
}
// ────────────────────────────────────────────────────────────────────────────

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
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
};

app.MapPost("/api/title", async (TitleRequest req, IConfiguration config, IHttpClientFactory factory) =>
{
    var apiKey = config["AnthropicApiKey"];
    if (string.IsNullOrEmpty(apiKey)) return Results.Problem("Cheia API nu este configurată.");

    var httpClient = factory.CreateClient();
    httpClient.DefaultRequestHeaders.Add("x-api-key", apiKey);
    httpClient.DefaultRequestHeaders.Add("anthropic-version", "2023-06-01");

    var requestBody = new AnthropicRequest(
        Model: "claude-sonnet-4-20250514",
        MaxTokens: 20,
        System: "You generate ultra-short chat titles. Reply with 2-3 words only — no punctuation, no quotes, no explanation.",
        Messages: [new ChatMessage("user", $"Summarize this message as a 2-3 word title: {req.Message}")]
    );

    var content = JsonContent.Create(requestBody, options: jsonOptions);
    var response = await httpClient.PostAsync("https://api.anthropic.com/v1/messages", content);
    if (!response.IsSuccessStatusCode) return Results.Problem("Eroare de la serviciul AI.");

    var result = await response.Content.ReadFromJsonAsync<AnthropicResponse>(jsonOptions);
    var title = result?.Content?.FirstOrDefault()?.Text ?? req.Message[..Math.Min(30, req.Message.Length)];
    return Results.Ok(new { title });
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

// Shut down the Python process cleanly when the .NET app stops
var lifetime = app.Services.GetRequiredService<IHostApplicationLifetime>();
lifetime.ApplicationStopping.Register(() =>
{
    if (pythonProcess is { HasExited: false })
    {
        pythonProcess.Kill(entireProcessTree: true);
        Console.WriteLine("✓ Python API server stopped.");
    }
});

app.Run();

record TitleRequest(string Message);
record ChatRequest(List<ChatMessage> Messages);
record ChatMessage(string Role, string Content);
record AnthropicTool(string Type, string Name);
record AnthropicRequest(string Model, int MaxTokens, string System, List<ChatMessage> Messages, List<AnthropicTool>? Tools = null);
record AnthropicResponse(List<AnthropicContent> Content);
record AnthropicContent(string Type, string? Text);
