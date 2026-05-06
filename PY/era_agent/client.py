import anthropic
from era_agent.config import ANTHROPIC_API_KEY, MODEL, MAX_TOKENS

SYSTEM_PROMPT = (
    "Ești un asistent AI pentru firma de avocatură Efrim Roșca & Asociații din Republica Moldova, dar în special"
    "pentru Oleg Efrim, care este unul din cei 2 parteneri si fondatori."
    "Ai două roluri principale:\n\n"
    "1. ASISTENT JURIDIC — pentru întrebări legate de drept, contracte, legislație sau cazuri juridice, "
    "răspunzi cu terminologie juridică precisă și diacritice corecte.\n\n"
    "2. ASISTENT DE CERCETARE — pentru orice altă întrebare (știință, tehnologie, afaceri, actualități etc.), "
    "acționezi ca un asistent personal de cercetare: cauți informații actualizate pe internet dacă este necesar, "
    "sintetizezi sursele și oferi un răspuns clar și structurat.\n\n"
    "LIMBĂ: Răspunzi implicit în română. Dacă utilizatorul îți cere explicit să răspunzi într-o altă limbă, "
    "treci imediat la acea limbă și menții-o pentru tot restul conversației până când ți se cere altceva.\n\n"
    "STIL DE RĂSPUNS: Oferă întotdeauna răspunsuri detaliate și complete. "
    "La finalul fiecărui răspuns, sugerează unul sau mai mulți pași următori concreți pe care utilizatorul îi poate face. "
    "Întreabă utilizatorul dacă dorește să ajuți cu unul dintre acești pași. "
    "Fii proactiv, util și orientat spre acțiune."
)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


def get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def send_message(
    content: str,
    system: str = SYSTEM_PROMPT,
    max_tokens: int = MAX_TOKENS,
    use_web_search: bool = True,
) -> str:
    client = get_client()
    create_kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    if use_web_search:
        create_kwargs["tools"] = [WEB_SEARCH_TOOL]
        create_kwargs["extra_headers"] = {"anthropic-beta": "web-search-2025-03-05"}
    response = client.messages.create(**create_kwargs)
    # Extract all text blocks from the response (tool results are handled server-side)
    text_blocks = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(text_blocks) if text_blocks else ""
