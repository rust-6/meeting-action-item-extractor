# Meeting Action-Item Extractor

Turns a meeting transcript into structured action items: **task, owner, deadline, confidence, status**.
Includes validation (missing owners, past dates, duplicates), a Streamlit UI, and an evaluation script.

## Screenshots

![Input screen](screenshot1.png)

![Results table](screenshot2.png)

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py          # upload/paste a transcript, click "Extract"
python extractor.py sample_meeting.txt --date 2026-11-03   # CLI, JSON output
python evaluate.py            # precision / recall / owner + deadline accuracy
```

Optional LLM mode (Claude): `export ANTHROPIC_API_KEY=...` then choose "LLM (Claude)" in the sidebar
or run `python extractor.py sample_meeting.txt --mode llm`.

## How it works

```
transcript -> split by speaker/sentence -> extract (rules OR LLM)
           -> remove duplicates -> validate -> table / CSV / JSON
```

1. **Segmentation**: `Speaker: text` lines are parsed; timestamps are stripped.
2. **Extraction (rules mode)**: a sentence is a candidate if it has a commitment/request cue
   ("I will", "can you", "needs to", "please"...). Owner comes from the speaker ("I'll ...")
   or a name mentioned in the sentence. Deadlines (Friday, tomorrow, 10 November, next Monday, in 3 days,
   ISO dates) are resolved relative to the meeting date.
3. **Extraction (LLM mode)**: Claude returns a strict JSON array following the same schema.
4. **Validation**: duplicate tasks are merged; items with no owner, no deadline, an invalid
   or past date, or confidence below the threshold are marked `needs review`.

## Output schema

| field | meaning |
|---|---|
| task | cleaned action description |
| owner | person responsible, or null |
| deadline | `YYYY-MM-DD` or null |
| confidence | 0-1 score (rules: based on cue, owner, deadline found) |
| status | `ok` or `needs review` |
| issues | list of validation problems |

## Evaluation

`python evaluate.py --verbose` runs the extractor on 9 hand-labelled meetings (`sample_meeting.txt`
+ `eval_cases.json`, 35 gold action items). Predicted tasks are matched to gold items by fuzzy text
similarity (>= 0.6), then owner and deadline are compared.

**Results (rules mode):**

| metric | score |
|---|---|
| Task detection precision | 0.80 |
| Task detection recall | 0.94 |
| Task detection F1 | 0.87 |
| Owner accuracy (matched tasks) | 30/33 (91%) |
| Deadline accuracy (matched tasks) | 30/33 (91%) |

**Where it fails (and why):**
- *Same task said twice in different words*, e.g. "Can you share the survey?" then "I can share them on Friday" -> extra item (no coreference resolution).
- *Owner phrased with extra words*: "I also need to..." is not matched as a self-assignment.
- *Corrections*: "I can't do tomorrow, I'll send it Wednesday" picks "tomorrow" instead of Wednesday.
- *Unsupported date phrases*: "in two weeks" (only digits are handled).
- *Compound sentences*: two tasks in one sentence are merged into one item.

These cases are what the optional LLM mode is meant to handle better.
The `needs review` flag catches many of them (missing owner or deadline).

## Limitations

- Rules mode only understands English and `Speaker: text` format.
- "next Friday" is treated as the Friday of next week (ambiguous in real speech).
- Pronouns ("do it", "that") are not resolved, so such tasks can be vague.
- A task discussed by several people over several turns may be split or missed.

## Ideas to extend

- Add more labelled transcripts (AMI / QMSum corpora) and compare rules vs LLM.
- Export to Google Calendar / Jira / Notion.
- Let users edit rows in the UI and save corrections as new gold data.
