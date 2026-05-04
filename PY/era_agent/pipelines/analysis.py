"""Document analysis pipeline — single Claude call returning summary + clauses."""

import json
import re

from era_agent.client import send_message


def analyze_document(text: str) -> dict:
    """
    Send the document to Claude once and get both the summary and clause
    extraction back in a single response.

    Returns a dict with keys: "summary" (str), "clauses" (str)
    Both fields are guaranteed to be markdown strings.
    """
    prompt = (
        "Analizează următorul document juridic și returnează STRICT un obiect JSON "
        "cu exact două câmpuri, AMBELE de tip STRING (text markdown), NU array-uri sau obiecte.\n\n"
        "{\n"
        '  "summary": "<text markdown>",\n'
        '  "clauses": "<text markdown>"\n'
        "}\n\n"
        "Conținutul fiecărui câmp:\n\n"
        "summary: un text markdown care include:\n"
        "  - Un rezumat concis al documentului (3-5 propoziții)\n"
        "  - Punctele cheie identificate (listă cu bullets)\n"
        "  - Clauze importante sau riscuri potențiale\n\n"
        "clauses: un text markdown formatat astfel pentru fiecare clauză:\n"
        "  ### Titlul clauzei\n"
        "  Conținutul relevant al clauzei.\n"
        "  **Observații / riscuri:** ...\n\n"
        "IMPORTANT: Răspunde DOAR cu JSON valid. Ambele valori TREBUIE să fie string-uri "
        "markdown, NU array-uri JSON. Nu adăuga text înainte sau după obiectul JSON.\n\n"
        f"Document:\n{text}"
    )

    raw = send_message(prompt)

    # Strip markdown code fences if Claude wraps the response in ```json ... ```
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        # If Claude returned non-JSON, treat the whole reply as the summary
        return {"summary": raw, "clauses": ""}

    return {
        "summary": _coerce_to_markdown(data.get("summary", "")),
        "clauses": _coerce_to_markdown(data.get("clauses", "")),
    }


def _coerce_to_markdown(value) -> str:
    """
    Defensive: Claude sometimes returns arrays/objects when asked for strings.
    Normalize anything we get into a markdown string the frontend can render.
    """
    if isinstance(value, str):
        return value

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                # Look for common keys (English + Romanian, with/without diacritics)
                title = (
                    item.get("title")
                    or item.get("titlu")
                    or item.get("titlul")
                    or item.get("tip")
                    or item.get("tipul")
                    or ""
                )
                content = (
                    item.get("content")
                    or item.get("continut")
                    or item.get("conținut")
                    or item.get("text")
                    or ""
                )
                notes = (
                    item.get("notes")
                    or item.get("observatii")
                    or item.get("observații")
                    or item.get("risks")
                    or item.get("riscuri")
                    or ""
                )

                if title:
                    parts.append(f"### {title}")
                if content:
                    parts.append(str(content))
                if notes:
                    parts.append(f"**Observații / riscuri:** {notes}")
                parts.append("")  # blank line between clauses
            else:
                parts.append(str(item))
        return "\n\n".join(p for p in parts if p).strip()

    if isinstance(value, dict):
        return "\n\n".join(f"**{k}:** {v}" for k, v in value.items())

    return str(value)
