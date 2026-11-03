"""Meeting Action-Item Extractor.

Two modes:
  rules : regex/heuristic extraction, no API key needed
  llm   : Claude extracts items as JSON (needs ANTHROPIC_API_KEY)

Both modes go through the same validation step
(date checks, missing owners, duplicate tasks, confidence threshold).
"""
import argparse
import json
import os
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
FULL_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]
MON_RE = "(?:" + "|".join(FULL_MONTHS) + "|" + "|".join(m[:3] for m in FULL_MONTHS) + ")"
WD_RE = "(?:" + "|".join(WEEKDAYS) + ")"
PREP = r"(?:\b(?:by|before|on|until|till|due)\s+)?"

SPEAKER_RE = re.compile(r"^\s*([A-Z][\w.'-]*(?: [A-Z][\w.'-]*)?)\s*:\s*(.+)$")
TIMESTAMP_RE = re.compile(r"^\s*\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*")
CUE_RE = re.compile(
    r"\b(will|we'll|need to|needs to|has to|have to|should|going to|can you|could you|"
    r"will you|would you|please|action item|follow up|take care of|responsible for)\b", re.I)
SELF_RE = re.compile(
    r"\b(?:i'll|i will|i can(?!'t|not)|i'm going to|i need to|i have to|let me)\b", re.I)
REQUEST_RE = re.compile(r"\b(action item|can you|could you|will you|would you|please)\b", re.I)

LEAD_WORDS = {
    "sure", "okay", "ok", "yes", "yeah", "great", "noted", "also", "and", "so", "alright",
    "right", "please", "i", "i'll", "we", "we'll", "you", "can", "could", "will", "should",
    "need", "needs", "to", "has", "have", "going", "am", "i'm", "let", "me", "someone",
    "somebody", "anyone", "everyone", "then", "thanks",
}


# ---------------------------------------------------------------- parsing
def parse_transcript(text):
    """Return a list of (speaker, utterance). Lines without a speaker join the previous turn."""
    turns = []
    for line in text.splitlines():
        line = TIMESTAMP_RE.sub("", line.strip())
        if not line:
            continue
        m = SPEAKER_RE.match(line)
        if m:
            turns.append((m.group(1).strip(), m.group(2).strip()))
        elif turns:
            turns[-1] = (turns[-1][0], turns[-1][1] + " " + line)
        else:
            turns.append(("Unknown", line))
    return turns


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ---------------------------------------------------------------- dates
def _month_day(today, mon, day):
    month = [m[:3] for m in FULL_MONTHS].index(mon[:3].lower()) + 1
    try:
        d = date(today.year, month, day)
        if d < today:
            d = d.replace(year=today.year + 1)
        return d
    except ValueError:
        return None


def parse_deadline(text, today):
    """Return (YYYY-MM-DD or None, matched phrase or None). Relative dates use `today` (meeting date)."""
    low = text.lower()

    m = re.search(PREP + r"(\d{4}-\d{2}-\d{2})\b", low)
    if m:
        try:
            return date.fromisoformat(m.group(1)).isoformat(), m.group(0)
        except ValueError:
            pass

    m = re.search(PREP + r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + MON_RE + r")\b", low)
    if m:
        d = _month_day(today, m.group(2), int(m.group(1)))
        if d:
            return d.isoformat(), m.group(0)

    m = re.search(PREP + r"\b(" + MON_RE + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", low)
    if m:
        d = _month_day(today, m.group(1), int(m.group(2)))
        if d:
            return d.isoformat(), m.group(0)

    m = re.search(PREP + r"\b(?:today|eod|end of (?:the )?day)\b", low)
    if m:
        return today.isoformat(), m.group(0)

    m = re.search(PREP + r"\btomorrow\b", low)
    if m:
        return (today + timedelta(days=1)).isoformat(), m.group(0)

    m = re.search(PREP + r"\bin (\d+) days?\b", low)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat(), m.group(0)

    m = re.search(PREP + r"\bnext week\b", low)
    if m:
        return (today + timedelta(days=7)).isoformat(), m.group(0)

    m = re.search(PREP + r"\b(?:end of (?:the )?week|eow|this week)\b", low)
    if m:
        ahead = (4 - today.weekday()) % 7  # coming Friday
        return (today + timedelta(days=ahead)).isoformat(), m.group(0)

    m = re.search(PREP + r"\b(next |this )?(" + WD_RE + r")\b", low)
    if m:
        prefix = (m.group(1) or "").strip()
        target = WEEKDAYS.index(m.group(2))
        ahead = (target - today.weekday()) % 7
        if ahead == 0:
            ahead = 7
        if prefix == "next" and target > today.weekday():
            ahead += 7  # assumption: "next Friday" = Friday of next week
        return (today + timedelta(days=ahead)).isoformat(), m.group(0)

    return None, None


# ---------------------------------------------------------------- rules mode
def find_owner(sentence, speaker, speakers):
    if SELF_RE.search(sentence):
        return speaker
    best = None
    for full in speakers:
        first = full.split()[0]
        m = re.search(r"\b" + re.escape(first) + r"\b", sentence, re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), full)
    return best[1] if best else None


def clean_task(sentence, first_names, phrase):
    t = sentence
    if phrase:
        t = re.sub(re.escape(phrase), "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    if first_names:
        names_alt = "|".join(re.escape(n) for n in first_names)
        t = re.sub(r"\s*,\s*(?:" + names_alt + r")[\s.!?]*$", "", t, flags=re.I)
    words = t.strip(" ,.;!?").split()
    skip = LEAD_WORDS | {n.lower() for n in first_names}
    while words and re.sub(r"[^\w']", "", words[0]).lower() in skip:
        words.pop(0)
    t = " ".join(words).strip(" ,.;!?")
    return t[:1].upper() + t[1:]


def extract_rules(transcript, today):
    turns = parse_transcript(transcript)
    speakers = sorted({s for s, _ in turns if s != "Unknown"})
    first_names = [s.split()[0] for s in speakers]
    items = []
    for speaker, text in turns:
        for sent in split_sentences(text):
            if len(sent.split()) < 4:
                continue
            if not (CUE_RE.search(sent) or SELF_RE.search(sent)):
                continue
            if sent.endswith("?") and not REQUEST_RE.search(sent):
                continue  # a plain question, not a request
            owner = find_owner(sent, speaker, speakers)
            deadline, phrase = parse_deadline(sent, today)
            task = clean_task(sent, first_names, phrase)
            if len(task.split()) < 2:
                continue
            conf = 0.4
            conf += 0.25 if owner else 0
            conf += 0.20 if deadline else 0
            conf += 0.10 if (SELF_RE.search(sent) or REQUEST_RE.search(sent)) else 0
            items.append({
                "task": task, "owner": owner, "deadline": deadline,
                "confidence": round(min(conf, 0.95), 2),
                "source_speaker": speaker, "source_text": sent,
            })
    return items


# ---------------------------------------------------------------- LLM mode
LLM_SYSTEM = """You extract action items from meeting transcripts.
Return ONLY a JSON array. Each element must be:
{"task": str, "owner": str or null, "deadline": "YYYY-MM-DD" or null, "confidence": number 0-1, "source_text": str}
Rules:
- Include only real commitments or assignments, not general discussion.
- Never invent owners or deadlines. Use null when unclear.
- Resolve relative dates ("Friday", "tomorrow", "next week") using the meeting date given by the user.
- Do not repeat the same task twice."""


def extract_llm(transcript, today, model=None):
    import anthropic  # imported lazily so rules mode works without it

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=model or os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=2000,
        system=LLM_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Meeting date: {today.isoformat()} ({WEEKDAYS[today.weekday()].title()})\n\nTranscript:\n{transcript}",
        }],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\[.*\]", raw, re.S)
    data = json.loads(m.group(0)) if m else []
    items = []
    for d in data:
        owner = d.get("owner")
        if isinstance(owner, str) and owner.strip().lower() in ("", "none", "null", "unknown", "n/a"):
            owner = None
        try:
            conf = float(d.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        items.append({
            "task": str(d.get("task", "")).strip(), "owner": owner,
            "deadline": d.get("deadline") or None, "confidence": round(conf, 2),
            "source_speaker": None, "source_text": d.get("source_text", ""),
        })
    return items


# ---------------------------------------------------------------- validation
def _sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def dedupe(items, threshold=0.8):
    kept, removed = [], 0
    for it in items:
        dup_idx = None
        for i, k in enumerate(kept):
            owners_compatible = (not k["owner"]) or (not it["owner"]) or k["owner"] == it["owner"]
            if owners_compatible and _sim(k["task"], it["task"]) >= threshold:
                dup_idx = i
                break
        if dup_idx is None:
            kept.append(it)
        else:
            removed += 1
            if it["confidence"] > kept[dup_idx]["confidence"]:
                kept[dup_idx] = it
    return kept, removed


def _valid_iso(s):
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def validate(items, today, review_threshold=0.6):
    for it in items:
        issues = []
        if not it["owner"]:
            issues.append("missing owner")
        if it["deadline"] and not _valid_iso(it["deadline"]):
            issues.append(f"invalid date '{it['deadline']}'")
            it["deadline"] = None
        if not it["deadline"]:
            issues.append("missing deadline")
        elif it["deadline"] < today.isoformat():
            issues.append("deadline in the past")
        if len(it["task"].split()) < 2:
            issues.append("task too short")
        it["issues"] = issues
        it["status"] = "needs review" if (issues or it["confidence"] < review_threshold) else "ok"
    return items


# ---------------------------------------------------------------- public API
def extract(transcript, meeting_date=None, mode="rules", review_threshold=0.6):
    today = meeting_date or date.today()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    raw = extract_llm(transcript, today) if mode == "llm" else extract_rules(transcript, today)
    items, removed = dedupe(raw)
    items = validate(items, today, review_threshold)
    return {"meeting_date": today.isoformat(), "mode": mode,
            "duplicates_removed": removed, "items": items}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Extract action items from a transcript")
    ap.add_argument("file")
    ap.add_argument("--date", default=None, help="meeting date YYYY-MM-DD (default: today)")
    ap.add_argument("--mode", choices=["rules", "llm"], default="rules")
    args = ap.parse_args()
    with open(args.file, encoding="utf-8") as f:
        print(json.dumps(extract(f.read(), args.date, args.mode), indent=2))
