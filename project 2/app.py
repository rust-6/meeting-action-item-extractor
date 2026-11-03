import json
import os
from datetime import date

import pandas as pd
import streamlit as st

from extractor import extract

st.set_page_config(page_title="Meeting Action-Item Extractor", page_icon="📝", layout="wide")
st.title("📝 Meeting Action-Item Extractor")
st.caption("Upload a transcript and get tasks, owners, deadlines and confidence scores.")

with st.sidebar:
    st.header("Settings")
    mode_label = st.radio("Extraction mode", ["Rules (no API key)", "LLM (Claude)"])
    mode = "llm" if mode_label.startswith("LLM") else "rules"
    if mode == "llm" and not os.getenv("ANTHROPIC_API_KEY"):
        st.warning("Set the ANTHROPIC_API_KEY environment variable to use LLM mode.")
    meeting_date = st.date_input("Meeting date", value=date.today())
    st.caption("Used to resolve words like 'Friday', 'tomorrow' and 'next week'.")
    threshold = st.slider("Needs-review threshold", 0.0, 1.0, 0.6, 0.05)

st.markdown("Transcript format: one turn per line, like `Priya: I will send the report by Friday.`")
uploaded = st.file_uploader("Upload transcript (.txt)", type=["txt"])

if uploaded:
    text = uploaded.read().decode("utf-8", errors="ignore")
    with st.expander("Transcript preview"):
        st.text(text)
else:
    default = ""
    if os.path.exists("sample_meeting.txt"):
        with open("sample_meeting.txt", encoding="utf-8") as f:
            default = f.read()
    text = st.text_area("...or paste a transcript", value=default, height=260)

if st.button("Extract action items", type="primary"):
    if not text.strip():
        st.warning("Please provide a transcript first.")
        st.stop()
    try:
        with st.spinner("Extracting..."):
            result = extract(text, meeting_date, mode, review_threshold=threshold)
    except Exception as e:  # e.g. missing API key or bad JSON from the model
        st.error(f"Extraction failed: {e}")
        st.stop()

    items = result["items"]
    if not items:
        st.info("No action items found.")
        st.stop()

    flagged = sum(1 for i in items if i["status"] != "ok")
    c1, c2, c3 = st.columns(3)
    c1.metric("Action items", len(items))
    c2.metric("Need review", flagged)
    c3.metric("Duplicates removed", result["duplicates_removed"])

    df = pd.DataFrame(items)[["task", "owner", "deadline", "confidence", "status", "issues"]]
    df["issues"] = df["issues"].apply(lambda x: ", ".join(x))
    st.dataframe(df, use_container_width=True, hide_index=True)

    d1, d2 = st.columns(2)
    d1.download_button("Download CSV", df.to_csv(index=False), "action_items.csv", "text/csv")
    d2.download_button("Download JSON", json.dumps(result, indent=2), "action_items.json", "application/json")

    with st.expander("Source sentences"):
        for i in items:
            st.markdown(f"- **{i['task']}** ← _{i['source_text']}_")
