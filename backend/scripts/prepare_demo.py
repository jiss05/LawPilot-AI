"""
Prepare the database for the management demo.

WHAT IT DOES
    1. Checks the backend is running and the databases are reachable.
    2. Logs in as an ADMIN (the password is typed hidden, never shown).
    3. Finds the editions that would spoil the demo:
         - test uploads made with Swagger's placeholder value "string"
         - earlier uploads of the Indian Contract Act (you upload it again
           LIVE during the demo, so old copies would give duplicate results)
    4. Shows the list and asks before changing anything.
    5. Withdraws them. Withdrawn editions are KEPT (history and audit trail)
       but are no longer used for search. Nothing is deleted.

HOW TO RUN (backend must be running; from backend/, venv active):
    python scripts/prepare_demo.py
    python scripts/prepare_demo.py --keep-latest   # keep the newest Contract Act
                                                   # copy active (for the optional
                                                   # "withdraw live" proof in Part 5)
"""

from __future__ import annotations

import argparse
import getpass
import sys

import httpx

JUNK = "string"                      # Swagger's placeholder value
DEMO_TITLE_WORDS = ("contract act",)  # titles of the Act uploaded live
LIVE_STATUSES = {"active", "pending"}


def is_junk(source: dict) -> bool:
    return any((source.get(k) or "").strip().lower() == JUNK
               for k in ("title", "source_type", "jurisdiction", "trust_tier"))


def is_demo_act(source: dict) -> bool:
    title = (source.get("title") or "").lower()
    return any(word in title for word in DEMO_TITLE_WORDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Withdraw old test uploads before the demo.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", help="admin email (asked if missing)")
    parser.add_argument("--keep-latest", action="store_true",
                        help="keep the newest Contract Act edition active")
    args = parser.parse_args()

    api = httpx.Client(base_url=args.base_url, timeout=30)

    # 1. Health ---------------------------------------------------------------
    try:
        ready = api.get("/api/v1/health/ready")
    except httpx.ConnectError:
        sys.exit("The backend is not running. Start it first (start_demo.bat).")
    print("Health:", ready.status_code, ready.json())
    if ready.status_code != 200:
        sys.exit("Databases not ready. Is the Docker PC on?")

    # 2. Login ----------------------------------------------------------------
    email = args.email or input("Admin email: ").strip()
    password = getpass.getpass("Admin password (hidden): ")
    login = api.post("/api/v1/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        sys.exit(f"Login failed: {login.status_code} {login.text}")
    api.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    # 3. Find editions to withdraw ---------------------------------------------
    sources = api.get("/api/v1/knowledge-sources").json()
    plan: list[tuple[dict, dict, str]] = []          # (source, version, why)
    for source in sources:
        if not (is_junk(source) or is_demo_act(source)):
            continue
        versions = api.get(f"/api/v1/knowledge-sources/{source['id']}/versions")
        if versions.status_code != 200:
            print(f"  ! could not read editions of {source['title']!r}: {versions.status_code}")
            continue
        for version in versions.json():
            if version["status"] in LIVE_STATUSES:
                why = "placeholder 'string' test upload" if is_junk(source) else "old copy of the demo Act"
                plan.append((source, version, why))

    if args.keep_latest:
        acts = [p for p in plan if p[2] == "old copy of the demo Act"]
        if acts:
            newest = max(acts, key=lambda p: p[1]["retrieved_at"])
            plan.remove(newest)
            print(f"Keeping active: {newest[0]['title']!r} ({newest[1]['retrieved_at'][:16]})")

    if not plan:
        print("\nNothing to clean. The database is ready for the demo.")
        return

    print(f"\n{len(plan)} edition(s) will be WITHDRAWN (kept in history, removed from search):\n")
    for source, version, why in plan:
        print(f"  - {source['title'][:50]:50}  uploaded {version['retrieved_at'][:16]}  [{why}]")

    if input("\nGo ahead? Type yes: ").strip().lower() != "yes":
        sys.exit("Nothing changed.")

    # 4. Withdraw -----------------------------------------------------------------
    failures = 0
    for source, version, why in plan:
        r = api.post(f"/api/v1/knowledge-sources/{source['id']}/versions/{version['id']}/withdraw",
                     json={"reason": f"Demo preparation: {why}"})
        ok = r.status_code == 200
        failures += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {source['title'][:50]}" + ("" if ok else f"  ({r.status_code} {r.text[:120]})"))

    print("\nDone." if not failures else f"\nDone with {failures} failure(s); see above.")


if __name__ == "__main__":
    main()
