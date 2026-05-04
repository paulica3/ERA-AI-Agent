"""Document analysis pipeline — single Claude call returning summary + clauses."""

import json
import re

from era_agent.client import send_message


def analyze_document(text: str) -> dict:
    """
    Send the document to Claude once and get both the summary and clause
    extraction back in a single response.

    Returns a dict with keys: "summary", "clauses"
    """
    prompt = (
        "Analizează următorul document juridic și returnează un obiect JSON cu exact două câmpuri:\n\n"
        "\"summary\": un rezumat complet care include:\n"
        "  - Un rezumat concis al documentului (3-5 propoziții)\n"
        "  - Punctele cheie identificate\n"
        "  - Clauze importante sau riscuri potențiale\n\n"
        "\"clauses\": toate clauzele importante din document, fiecare cu:\n"
        "  - Titlul/tipul clauzei\n"
        "  - Conținutul relevant\n"
        "  - Observații sau riscuri\n\n"
        "Răspunde DOAR cu JSON valid. Nu adăuga text înainte sau după JSON.\n\n"
        f"Document:\n{text}"
    )

    raw = send_message(prompt)

    # Strip markdown code fences if Claude wraps the response in ```json ... ```
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

    data = json.loads(clean)
    return {
        "summary": data.get("summary", ""),
        "clauses": data.get("clauses", ""),
    }
