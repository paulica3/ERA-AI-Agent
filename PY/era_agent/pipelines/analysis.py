"""Document analysis and summarization pipeline."""

from era_agent.client import send_message


def summarize(text: str) -> str:
    prompt = (
        "Analizează următorul document juridic și oferă:\n"
        "1. Un rezumat concis (3-5 propoziții)\n"
        "2. Punctele cheie identificate\n"
        "3. Clauze importante sau riscuri potențiale\n\n"
        f"Document:\n{text}"
    )
    return send_message(prompt)


def extract_clauses(text: str) -> str:
    prompt = (
        "Extrage toate clauzele importante din următorul document juridic. "
        "Pentru fiecare clauză, oferă:\n"
        "- Titlul/tipul clauzei\n"
        "- Conținutul relevant\n"
        "- Observații sau riscuri\n\n"
        f"Document:\n{text}"
    )
    return send_message(prompt)
