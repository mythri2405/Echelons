#!/usr/bin/env python3
"""Run the evaluation suite and print a number you can defend.

    python3 eval/run.py                     # in-process, no server needed
    python3 eval/run.py --url http://127.0.0.1:8000
    python3 eval/run.py --category refusal --verbose
    python3 eval/run.py --repeat 3          # same cases N times, for variance

Every check is mechanical. Nothing here asks a model to grade another model,
because a suite whose purpose is evidence cannot rest on the same machinery it
is testing.

Exit code is 1 if any case fails, so this can gate a commit.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import checks  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases.jsonl"


def load_cases(path: Path, category: str | None) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [c for c in cases if not category or c["category"] == category]


def ask_direct(case: dict, provider: str) -> dict:
    from backend import chat

    return chat.answer(case["message"], detection=case.get("record"), provider=provider)


def ask_http(case: dict, provider: str, url: str) -> dict:
    body = {"message": case["message"], "provider": provider}
    if case.get("record"):
        body["detection_record"] = case["record"]
    request = urllib.request.Request(url.rstrip("/") + "/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def run_case(case: dict, provider: str, url: str | None, attempts: int = 6) -> dict:
    # Free tiers rate-limit, and a suite that reports a limit as a failure is
    # measuring the provider's billing plan rather than the assistant.
    last = ""
    for attempt in range(attempts):
        try:
            result = ask_http(case, provider, url) if url else ask_direct(case, provider)
            break
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if "rate limit" not in last.lower() and "429" not in last:
                return {"case": case, "error": last, "results": []}
            # Free-tier windows are per minute, so back off into the next one.
            time.sleep(min(2 ** attempt, 20) + random.random() * 3)
    else:
        return {"case": case, "error": last, "results": []}

    # The checks need to know what the model was allowed to see, so that a
    # number quoted from the operator's own message is not counted as invented.
    result["_record"] = case.get("record") or {}
    result["_message"] = case["message"]

    outcomes = []
    for name in checks.ALWAYS:
        ok, detail = checks.CHECKS[name](result, None)
        outcomes.append({"check": name, "ok": ok, "detail": detail})
    for name, expected in case["expect"].items():
        if name in checks.ALWAYS:
            continue
        ok, detail = checks.CHECKS[name](result, expected)
        outcomes.append({"check": name, "ok": ok, "detail": detail})

    return {"case": case, "error": None, "results": outcomes, "answer": result.get("answer", "")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="run against a live backend instead of in-process")
    parser.add_argument("--provider", default="groq", help="LLM backend (default groq)")
    parser.add_argument("--category", help="run only one category")
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the suite N times; generation is not deterministic")
    parser.add_argument("--workers", type=int, default=3,
                        help="parallel requests; keep low on a free tier")
    parser.add_argument("--verbose", action="store_true", help="print failing answers")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()

    cases = load_cases(CASES, args.category)
    if not cases:
        print("No cases matched.", file=sys.stderr)
        return 1

    runs = cases * args.repeat
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outcomes = list(pool.map(lambda c: run_case(c, args.provider, args.url), runs))

    if args.as_json:
        print(json.dumps(outcomes, indent=2, default=str))

    passed = [o for o in outcomes if not o["error"] and all(r["ok"] for r in o["results"])]
    failed = [o for o in outcomes if o not in passed]

    by_category: dict[str, Counter] = defaultdict(Counter)
    for outcome in outcomes:
        by_category[outcome["case"]["category"]]["total"] += 1
        if outcome in passed:
            by_category[outcome["case"]["category"]]["pass"] += 1

    check_failures: Counter = Counter()
    for outcome in failed:
        for result in outcome["results"]:
            if not result["ok"]:
                check_failures[result["check"]] += 1

    if not args.as_json:
        print(f"{'category':12} {'pass':>8}")
        print(f"{'-' * 12} {'-' * 8}")
        for category in sorted(by_category):
            counts = by_category[category]
            print(f"{category:12} {counts['pass']:>4}/{counts['total']:<4}")
        print(f"{'-' * 12} {'-' * 8}")
        print(f"{'TOTAL':12} {len(passed):>4}/{len(outcomes):<4}")

        if failed:
            print("\nFAILURES")
            for outcome in failed:
                case = outcome["case"]
                if outcome["error"]:
                    print(f"  {case['id']:4} {case['category']:10} ERROR {outcome['error']}")
                    continue
                bad = [r for r in outcome["results"] if not r["ok"]]
                print(f"  {case['id']:4} {case['category']:10} {case['message'][:52]}")
                for result in bad:
                    print(f"       {result['check']}: {result['detail']}")
                if args.verbose:
                    print("       ---")
                    for line in outcome["answer"].splitlines()[:12]:
                        print(f"       | {line}")
            print("\nby check: " + ", ".join(f"{k} {v}" for k, v in check_failures.most_common()))

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
