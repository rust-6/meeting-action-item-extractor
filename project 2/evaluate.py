"""Score the extractor against hand-labelled meetings.

Cases come from:
  - sample_meeting.txt + sample_gold.json  (the simple demo meeting)
  - eval_cases.json                        (more meetings, incl. messy ones)

To add a case, append {"name", "date", "transcript": [lines], "gold": [...]} to eval_cases.json.
Usage: python evaluate.py [--mode rules|llm] [--verbose]
"""
import argparse
import json
import os
from difflib import SequenceMatcher

from extractor import extract


def sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def load_cases():
    cases = []
    if os.path.exists("sample_meeting.txt") and os.path.exists("sample_gold.json"):
        with open("sample_meeting.txt", encoding="utf-8") as f:
            transcript = f.read()
        with open("sample_gold.json", encoding="utf-8") as f:
            gold = json.load(f)
        cases.append({"name": "sample_meeting", "date": "2026-11-03",
                      "transcript": transcript, "gold": gold})
    if os.path.exists("eval_cases.json"):
        with open("eval_cases.json", encoding="utf-8") as f:
            for c in json.load(f):
                c["transcript"] = "\n".join(c["transcript"])
                cases.append(c)
    return cases


def score_case(case, mode):
    pred = extract(case["transcript"], case["date"], mode)["items"]
    gold = case["gold"]
    used, tp, owner_ok, date_ok, notes = set(), 0, 0, 0, []
    for g in gold:
        best, best_s = None, 0.0
        for i, p in enumerate(pred):
            if i in used:
                continue
            s = sim(g["task"], p["task"])
            if s > best_s:
                best, best_s = i, s
        if best is not None and best_s >= 0.6:
            used.add(best)
            tp += 1
            p = pred[best]
            if g["owner"] == p["owner"]:
                owner_ok += 1
            else:
                notes.append(f"  OWNER   : '{g['task']}' expected {g['owner']}, got {p['owner']}")
            if g["deadline"] == p["deadline"]:
                date_ok += 1
            else:
                notes.append(f"  DEADLINE: '{g['task']}' expected {g['deadline']}, got {p['deadline']}")
        else:
            notes.append(f"  MISSED  : {g['task']}")
    for i, p in enumerate(pred):
        if i not in used:
            notes.append(f"  EXTRA   : {p['task']}")
    return {"tp": tp, "n_pred": len(pred), "n_gold": len(gold),
            "owner_ok": owner_ok, "date_ok": date_ok, "notes": notes}


def prf(tp, n_pred, n_gold):
    p = tp / n_pred if n_pred else 0
    r = tp / n_gold if n_gold else 0
    f = 2 * p * r / (p + r) if p + r else 0
    return p, r, f


def main(mode, verbose):
    totals = {"tp": 0, "n_pred": 0, "n_gold": 0, "owner_ok": 0, "date_ok": 0}
    for case in load_cases():
        r = score_case(case, mode)
        for k in totals:
            totals[k] += r[k]
        p, rc, f = prf(r["tp"], r["n_pred"], r["n_gold"])
        print(f"{case['name']:<32} P={p:.2f} R={rc:.2f} F1={f:.2f}  "
              f"owner {r['owner_ok']}/{r['tp']}  deadline {r['date_ok']}/{r['tp']}")
        if verbose:
            print("\n".join(r["notes"]))
    p, rc, f = prf(totals["tp"], totals["n_pred"], totals["n_gold"])
    print("\n=== OVERALL ===")
    print(f"Task detection   precision={p:.2f} recall={rc:.2f} F1={f:.2f}  "
          f"({totals['tp']} matched / {totals['n_gold']} gold / {totals['n_pred']} predicted)")
    print(f"Owner accuracy (matched tasks)    : {totals['owner_ok']}/{totals['tp']}")
    print(f"Deadline accuracy (matched tasks) : {totals['date_ok']}/{totals['tp']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "llm"], default="rules")
    ap.add_argument("--verbose", action="store_true", help="show misses and wrong fields")
    args = ap.parse_args()
    main(args.mode, args.verbose)
