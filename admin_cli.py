#!/usr/bin/env python3
"""
admin_cli.py — Manage contests from the command line
Requires: pip install requests

Usage:
  python admin_cli.py create-contest  --token SECRET --base-url https://your-app.railway.app
  python admin_cli.py set-answers     --token SECRET --base-url https://your-app.railway.app --contest-id 1
  python admin_cli.py list-contests   --base-url https://your-app.railway.app
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("Install requests first: pip install requests")
    sys.exit(1)

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def api(base, path, method="GET", token=None, body=None):
    url     = base.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    resp = requests.request(method, url, headers=headers,
                            json=body, timeout=15)
    return resp.status_code, resp.json()


def create_contest(args):
    start = now_ist() + timedelta(hours=2)
    end   = now_ist() + timedelta(hours=8)

    payload = {
        "title":       input("Contest title: "),
        "description": input("Description: "),
        "entry_fee":   float(input("Entry fee (₹): ") or 99),
        "start_time":  start.isoformat(),
        "end_time":    end.isoformat(),
        "category":    input("Category [cricket]: ") or "cricket",
        "max_entries": int(input("Max entries [5000]: ") or 5000),
        "status":      "upcoming",
        "questions":   [],
    }

    print("\nAdd questions (press Enter with empty text to stop):")
    while True:
        qt = input("  Question text: ").strip()
        if not qt:
            break
        qtype = input("  Type [single_choice/range]: ").strip() or "single_choice"
        points = int(input("  Points [50]: ") or 50)
        opts = []
        if qtype == "single_choice":
            raw = input("  Options (comma-separated): ")
            opts = [o.strip() for o in raw.split(",") if o.strip()]
        payload["questions"].append({
            "question_text": qt, "q_type": qtype,
            "options": opts, "points": points
        })

    status, resp = api(args.base_url, "/api/admin/contests",
                       method="POST", token=args.token, body=payload)
    print(f"\nStatus {status}: {json.dumps(resp, indent=2)}")


def set_answers(args):
    # First fetch questions
    _, detail = api(args.base_url, f"/api/contests/{args.contest_id}")
    if "questions" not in detail:
        print("Contest not found or no questions.")
        return

    answers = {}
    for q in detail["questions"]:
        print(f"\nQ{q['id']}: {q['question_text']}  [{q['q_type']}]")
        if q.get("options"):
            print("  Options:", ", ".join(q["options"]))
        ans = input("  Correct answer: ").strip()
        answers[str(q["id"])] = ans

    status, resp = api(args.base_url, f"/api/admin/contests/{args.contest_id}/set-answers",
                       method="POST", token=args.token, body=answers)
    print(f"\nStatus {status}: {json.dumps(resp, indent=2)}")


def list_contests(args):
    _, contests = api(args.base_url, "/api/contests")
    if not isinstance(contests, list):
        print(contests)
        return
    print(f"\n{'ID':>4}  {'Status':10}  {'Title':40}  {'Entry':8}  {'Pool':10}")
    print("-" * 80)
    for c in contests:
        print(f"{c['id']:>4}  {c['status']:10}  {c['title'][:40]:40}  "
              f"₹{c['entry_fee']:>6}  ₹{c['prize_pool']:>8}")


def main():
    parser = argparse.ArgumentParser(description="Smart Predictor League Admin CLI")
    parser.add_argument("command", choices=["create-contest", "set-answers", "list-contests"])
    parser.add_argument("--base-url", default="http://localhost:5000")
    parser.add_argument("--token",    default="admin-secret-change-me")
    parser.add_argument("--contest-id", type=int, default=1)
    args = parser.parse_args()

    if args.command == "create-contest":
        create_contest(args)
    elif args.command == "set-answers":
        set_answers(args)
    elif args.command == "list-contests":
        list_contests(args)


if __name__ == "__main__":
    main()
