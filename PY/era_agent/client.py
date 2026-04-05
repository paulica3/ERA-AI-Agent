import anthropic
from era_agent.config import ANTHROPIC_API_KEY, MODEL, MAX_TOKENS

SYSTEM_PROMPT = (
    "Ești un asistent juridic AI pentru firma de avocatură Efrim Roșca & Asociații "
    "din Republica Moldova. Răspunzi întotdeauna în limba română, cu terminologie "
    "juridică precisă și diacritice corecte. Ești profesionist, concis și precis."
)


def get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def send_message(content: str, system: str = SYSTEM_PROMPT) -> str:
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text
