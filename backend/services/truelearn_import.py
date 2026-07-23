"""Parses a TrueLearn "My Notes" export (.xlsx): one row per note the
student wrote on a TrueLearn question, with columns including Topic,
Question ID (Root ID), and Note. The Question ID is a stable per-question
identifier, used elsewhere to dedupe against notes already turned into
cards from an earlier export."""
from pathlib import Path
from typing import Any, Dict, List

import openpyxl

REQUIRED_COLUMNS = {"topic", "question id (root id)", "note"}


class TrueLearnImportError(RuntimeError):
    pass


def parse_notes(path: Path) -> List[Dict[str, Any]]:
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:  # noqa: BLE001 - surface as a clear import error
        raise TrueLearnImportError(f"Couldn't read this as an Excel file: {exc}") from exc

    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise TrueLearnImportError("The spreadsheet is empty.")

    header = [str(h or "").strip().lower() for h in rows[0]]
    if not REQUIRED_COLUMNS.issubset(header):
        raise TrueLearnImportError(
            "This doesn't look like a TrueLearn Notes export -- expected columns "
            "'Topic', 'Question ID (Root ID)', and 'Note'."
        )
    topic_i = header.index("topic")
    id_i = header.index("question id (root id)")
    note_i = header.index("note")

    notes = []
    for row in rows[1:]:
        if row is None or len(row) <= max(topic_i, id_i, note_i):
            continue
        question_id = str(row[id_i]).strip() if row[id_i] is not None else ""
        note = str(row[note_i]).strip() if row[note_i] is not None else ""
        topic = str(row[topic_i]).strip() if row[topic_i] is not None else ""
        if not question_id or not note:
            continue
        notes.append({"question_id": question_id, "topic": topic, "note": note})
    return notes
