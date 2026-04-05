"""ERA AI Agent — CLI for testing pipelines."""

import argparse
import sys
import os

# Fix Windows terminal encoding for Romanian characters (ă, â, î, ș, ț)
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")

from era_agent.config import ANTHROPIC_API_KEY


def cmd_chat(args):
    from era_agent.client import send_message
    print("ERA AI Agent — Mod conversație (scrie 'exit' pentru a ieși)\n")
    while True:
        try:
            user_input = input("Tu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nLa revedere!")
            break
        if not user_input or user_input.lower() == "exit":
            print("La revedere!")
            break
        response = send_message(user_input)
        print(f"\nERA AI: {response}\n")


def cmd_analyze(args):
    from era_agent.ingestion.pdf import extract_text as pdf_extract
    from era_agent.ingestion.docx import extract_text as docx_extract
    from era_agent.pipelines.analysis import summarize

    path = args.file
    if path.lower().endswith(".pdf"):
        text = pdf_extract(path)
    elif path.lower().endswith(".docx"):
        text = docx_extract(path)
    else:
        print("Format neacceptat. Utilizați PDF sau DOCX.")
        sys.exit(1)

    print(f"Document încărcat: {path} ({len(text)} caractere)\n")
    print("Se analizează...\n")
    result = summarize(text)
    print(result)


def main():
    parser = argparse.ArgumentParser(description="ERA AI Agent")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("chat", help="Conversație liberă cu agentul")

    analyze_parser = subparsers.add_parser("analyze", help="Analizează un document")
    analyze_parser.add_argument("file", help="Calea către fișierul PDF sau DOCX")

    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("Eroare: ANTHROPIC_API_KEY nu este setat.")
        print("Copiați .env.example în .env și adăugați cheia API.")
        sys.exit(1)

    if args.command == "chat":
        cmd_chat(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
