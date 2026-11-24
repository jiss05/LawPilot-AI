"""
Hybrid retrieval demo in the terminal (SCRUM-16).

Ask questions in plain English and see which sections of the law the
system finds, with their citation and WHICH search found each one:
    MEANING   = vector search in Qdrant (finds it even with different words)
    WORDS     = keyword search in PostgreSQL (exact legal terms)
    both      = found by both -> ranked higher (Reciprocal Rank Fusion)

HOW TO RUN (backend must be running; from backend/):
    .venv/Scripts/python.exe scripts/demo_search.py
    .venv/Scripts/python.exe scripts/demo_search.py --email you@example.com --top 3

It logs in once (password hidden), then keeps asking questions.
Press Enter on an empty line to quit.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import textwrap

import httpx

BOLD, DIM, GREEN, CYAN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[36m", "\033[33m", "\033[0m"

CHANNEL_NAMES = {"vector": "MEANING (Qdrant)", "keyword": "WORDS (PostgreSQL)"}


def show(response: dict) -> None:
    print(f"\n{DIM}Searched by meaning: {response['vector_candidates']} candidates | "
          f"by exact words: {response['keyword_candidates']} candidates | "
          f"merged in {response['took_ms']} ms{RESET}")
    if response.get("degraded"):
        print(f"{YELLOW}Note: {', '.join(response['degraded'])} search unavailable; answered with the rest.{RESET}")
    if not response["results"]:
        print(f"{YELLOW}No matching law found.{RESET}")
        return
    for rank, r in enumerate(response["results"], start=1):
        loc, src = r["location"], r["source"]
        pages = loc["page_start"] if loc["page_start"] == loc["page_end"] else f"{loc['page_start']}-{loc['page_end']}"
        citation = src.get("citation") or f"{loc['section_ref']}, p. {pages}"
        found_by = " + ".join(CHANNEL_NAMES.get(c, c) for c in r["channels"])
        print(f"\n{BOLD}{GREEN}#{rank}  {citation}{RESET}   {DIM}score {r['score']:.4f}{RESET}")
        print(f"    {CYAN}{src['source_title']}{RESET}  ({src.get('trust_tier') or '-'}, {src.get('jurisdiction') or '-'})")
        print(f"    Found by: {BOLD}{found_by}{RESET}")
        text = " ".join(r["text"].split())
        preview = text[:350] + ("..." if len(text) > 350 else "")
        print(textwrap.fill(preview, 92, initial_indent="    ", subsequent_indent="    "))


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid search demo in the terminal.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", help="login email (asked if missing)")
    parser.add_argument("--top", type=int, default=3, help="how many results to show (default 3)")
    args = parser.parse_args()

    api = httpx.Client(base_url=args.base_url, timeout=60)
    try:
        api.get("/api/v1/health/live")
    except httpx.ConnectError:
        sys.exit("The backend is not running. Start it first (start_demo.bat).")

    email = args.email or input("Email: ").strip()
    password = getpass.getpass("Password (hidden): ")
    login = api.post("/api/v1/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        sys.exit(f"Login failed: {login.status_code} {login.text}")
    api.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    print(f"\n{BOLD}LawPilot hybrid search.{RESET} Ask a legal question. Empty line to quit.")
    while True:
        try:
            question = input(f"\n{BOLD}Question > {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        r = api.post("/api/v1/research/search",
                     json={"query": question, "top_k": args.top, "jurisdictions": ["India"]})
        if r.status_code != 200:
            print(f"{YELLOW}Search failed: {r.status_code} {r.text[:200]}{RESET}")
            continue
        show(r.json())
    print("Bye.")


if __name__ == "__main__":
    main()
