"""Orchestrates the pipeline: raw Source -> extracted text/media -> Claude ->
CardDraft objects. This is the only module that talks to both the storage
layer and the transcription/video/claude_client services."""
import html
import re
import shutil
from pathlib import Path
from typing import List, Optional

from .. import config
from ..models import CardDraft, CardType, MediaItem, MediaKind, Source, SourceStatus, SourceType
from ..storage import store
from . import claude_client, transcription, truelearn_import, video


def process_source(source: Source) -> Source:
    source.status = SourceStatus.processing
    source.error = None
    store.update_source(source)

    try:
        if source.type == SourceType.text:
            source.extracted_text = source.raw_text or ""

        elif source.type == SourceType.image:
            path = config.UPLOAD_DIR / source.stored_filename
            result = claude_client.caption_image(path)
            media_filename = f"{source.id}_{source.stored_filename}"
            shutil.copy(path, config.MEDIA_DIR / media_filename)
            media = MediaItem(
                filename=media_filename,
                mime_type=_guess_mime(path),
                kind=MediaKind.uploaded_image,
                source_id=source.id,
                caption=result["description"],
            )
            store.add_media(media)
            source.media_ids = [media.id]
            source.highlighted_excerpts = result["highlighted_excerpts"]
            source.extracted_text = _combine_description_and_highlights(
                result["description"], result["highlighted_excerpts"]
            )

        elif source.type == SourceType.audio:
            path = config.UPLOAD_DIR / source.stored_filename
            source.extracted_text = transcription.transcribe(path)

        elif source.type == SourceType.video:
            path = config.UPLOAD_DIR / source.stored_filename
            audio_path = video.extract_audio(path, config.UPLOAD_DIR)
            transcript = transcription.transcribe(audio_path)

            frames = video.extract_keyframes(path, config.MEDIA_DIR)
            media_ids = []
            all_highlights = []
            for frame_path, timestamp in frames:
                result = claude_client.caption_image(frame_path)
                media = MediaItem(
                    filename=frame_path.name,
                    mime_type="image/jpeg",
                    kind=MediaKind.video_frame,
                    source_id=source.id,
                    timestamp_seconds=timestamp,
                    caption=result["description"],
                )
                store.add_media(media)
                media_ids.append(media.id)
                all_highlights.extend(result["highlighted_excerpts"])

            source.media_ids = media_ids
            source.highlighted_excerpts = all_highlights
            source.extracted_text = transcript

        elif source.type == SourceType.truelearn_notes:
            path = config.UPLOAD_DIR / source.stored_filename
            all_notes = truelearn_import.parse_notes(path)
            seen = store.get_truelearn_seen_ids()
            new_notes = [n for n in all_notes if n["question_id"] not in seen]

            source.truelearn_row_ids = [n["question_id"] for n in new_notes]
            if not new_notes:
                source.extracted_text = (
                    f"(No new notes to import -- all {len(all_notes)} note(s) in this "
                    "file were already turned into cards from a previous import.)"
                )
            else:
                blocks = [
                    f"[Topic: {n['topic']}] (id {n['question_id']})\n{n['note']}" for n in new_notes
                ]
                source.extracted_text = "\n\n".join(blocks)

        source.status = SourceStatus.done

    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        source.status = SourceStatus.error
        source.error = str(exc)

    store.update_source(source)
    return source


def _guess_mime(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _combine_description_and_highlights(description: str, highlights: List[str]) -> str:
    text = description
    if highlights:
        text += "\n\nHIGHLIGHTED BY STUDENT:\n" + "\n".join(f"- {h}" for h in highlights)
    return text


_HIGHLIGHT_RE = re.compile(r"==(.+?)==")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_UNDERLINE_RE = re.compile(r"__(.+?)__")
_ITALIC_RE = re.compile(r"\*(.+?)\*")


def _render_explanation(points: List[str]) -> str:
    """Build guaranteed-safe HTML from plain-text bullet points instead of
    trusting an LLM to hand-write valid HTML. Escaping happens first, so a
    stray '<' or '&' in the model's text can never leak through as a broken
    tag; the markdown-lite ==highlight== marker is only converted to <mark>
    afterward, on already-safe text, so Claude never controls raw HTML."""
    items = []
    for p in points:
        if not isinstance(p, str):
            continue
        cleaned = p.strip().lstrip("-*•").strip()
        if cleaned:
            items.append(cleaned)
    if not items:
        return ""
    rendered = []
    for item in items:
        escaped = html.escape(item)
        escaped = _HIGHLIGHT_RE.sub(r"<mark>\1</mark>", escaped)
        rendered.append(f"<li>{escaped}</li>")
    return "<ul>" + "".join(rendered) + "</ul>"


def _render_question_html(text: str) -> str:
    """Same safe pattern as _render_explanation: escape first, then convert
    a constrained markdown-lite syntax (**bold**, __underline__, *italic*)
    into real tags on the already-escaped text."""
    escaped = html.escape((text or "").strip())
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _UNDERLINE_RE.sub(r"<u>\1</u>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    return escaped


def _apply_tag_root(tags: List[str], root: str) -> List[str]:
    """Prepend `root` to every tag so the deck name is always the shared
    parent in Anki's tag tree (e.g. root='Pharm' turns 'CardiacDrugs' into
    'Pharm::CardiacDrugs'). Enforced here rather than left to the prompt,
    the same lesson as max_cards -- an LLM instruction is a suggestion, not
    a guarantee."""
    root = root.strip()
    if not root:
        return tags
    prefix = f"{root}::"
    return [t if t == root or t.startswith(prefix) else f"{prefix}{t}" for t in tags]


def _strip_tag_root(tags: List[str], root: str) -> List[str]:
    """Inverse of _apply_tag_root -- kept only for the migration that
    briefly stripped the deck-root prefix before it was restored; drops a
    bare root tag entirely and strips 'root::' off anything nested under
    it."""
    root = root.strip()
    if not root:
        return tags
    prefix = f"{root}::"
    stripped = []
    for t in tags:
        if t == root:
            continue
        stripped.append(t[len(prefix):] if t.startswith(prefix) else t)
    return stripped


def build_cards_from_sources(
    source_ids: List[str],
    deck: str,
    card_type: CardType,
    subject_hint: Optional[str],
    instructions: Optional[str],
    max_cards: int,
) -> List[CardDraft]:
    sources = [store.get_source(sid) for sid in source_ids]
    sources = [s for s in sources if s is not None]
    if not sources:
        raise ValueError("No valid sources selected.")

    not_ready = [s.name for s in sources if s.status != SourceStatus.done]
    if not_ready:
        raise ValueError(f"These sources are not processed yet: {', '.join(not_ready)}")

    context_chunks = []
    for s in sources:
        header = f"== Source: {s.name} ({s.type.value}) =="
        chunk = f"{header}\n{s.extracted_text or ''}"

        # Video keyframes aren't embedded in cards, but their captions (and any
        # student highlights spotted in them) are folded in as text so Claude
        # still knows what was shown on screen.
        if s.type == SourceType.video and s.media_ids:
            frame_lines = []
            for mid in s.media_ids:
                m = store.get_media(mid)
                if not m or not m.caption:
                    continue
                if m.timestamp_seconds is not None:
                    minutes, seconds = divmod(int(m.timestamp_seconds), 60)
                    label = f"{minutes}:{seconds:02d}"
                else:
                    label = "?"
                frame_lines.append(f"- [{label}] {m.caption}")
            if frame_lines:
                chunk += "\n\nVisual moments in this video:\n" + "\n".join(frame_lines)
            if s.highlighted_excerpts:
                chunk += "\n\nHIGHLIGHTED BY STUDENT (seen in a video frame):\n" + "\n".join(
                    f"- {h}" for h in s.highlighted_excerpts
                )

        context_chunks.append(chunk)

    # Only count a TrueLearn source once it actually has new (undeduped) rows
    # -- a fully-deduped source (0 new rows) shouldn't force auto_count on
    # for the whole batch if it's mixed with an unrelated source that does
    # want normal max_cards-based generation.
    truelearn_row_count = sum(len(s.truelearn_row_ids) for s in sources if s.type == SourceType.truelearn_notes)
    has_truelearn_notes = truelearn_row_count > 0
    auto_count = any(s.highlighted_excerpts for s in sources) or has_truelearn_notes
    auto_count_cap = None
    if auto_count:
        # A hard upper bound on card count: one per highlighted excerpt plus
        # one per new TrueLearn row. Without this, "auto_count" gave Claude
        # no ceiling at all and it would sometimes split a single row's note
        # into several atomic cards, badly over-producing.
        auto_count_cap = sum(len(s.highlighted_excerpts) for s in sources) + truelearn_row_count

    raw_cards = claude_client.generate_cards(
        context_text="\n\n".join(context_chunks),
        card_type=card_type,
        subject_hint=subject_hint,
        instructions=instructions,
        max_cards=max_cards,
        auto_count=auto_count,
        auto_count_cap=auto_count_cap,
        has_truelearn_notes=has_truelearn_notes,
    )

    cards = []
    for raw in raw_cards:
        tags = [t.strip() for t in raw.get("tags", []) if t.strip()]
        common = dict(
            card_type=card_type,
            explanation=_render_explanation(raw.get("explanation_points", [])),
            tags=_apply_tag_root(tags, deck),
            deck=deck,
            source_ids=source_ids,
        )
        if card_type == CardType.basic:
            cards.append(
                CardDraft(
                    question=_render_question_html(raw.get("question", "")),
                    answer=raw.get("answer", "").strip(),
                    **common,
                )
            )
        else:
            cards.append(
                CardDraft(
                    cloze_text=raw.get("cloze_text", "").strip(),
                    **common,
                )
            )

    store.add_cards(cards)

    # Only mark these Question IDs as "already carded" now that cards were
    # actually generated from them -- if generation had failed above, the
    # rows would still be reported as new next time, matching the same
    # commit-only-on-success pattern used for Daily Notes' checkpoint.
    truelearn_ids = [rid for s in sources if s.type == SourceType.truelearn_notes for rid in s.truelearn_row_ids]
    if truelearn_ids:
        store.add_truelearn_seen_ids(truelearn_ids)

    return cards


def _is_daily_notes_card(card: CardDraft) -> bool:
    return any(t == "Daily Notes" or t.endswith("::Daily Notes") for t in card.tags)


def push_pending_daily_notes_cards() -> None:
    """Best-effort push of any not-yet-synced Daily Notes cards straight to
    Anki. Called right after nightly generation, and again periodically by
    the scheduler (see scheduler.py) -- so if Anki desktop wasn't open at
    generation time, the cards don't just sit there: they get pushed
    automatically the next time Anki (and this retry job) both happen to be
    running, with no manual step required."""
    from . import ankiconnect_client

    pending = [c for c in store.list_cards() if not c.archived and c.included and _is_daily_notes_card(c)]
    if not pending:
        return

    try:
        result = ankiconnect_client.push_cards(pending)
    except ankiconnect_client.AnkiConnectError as exc:
        store.mark_daily_notes_pushed(0, error=str(exc))
        return

    pushed_ids = set(result["added"]) | set(result["updated"])
    for card in pending:
        if card.id in pushed_ids:
            card.archived = True
            card.included = False
            store.update_card(card)

    error = f"{len(result['failed'])} card(s) failed to push." if result["failed"] else None
    store.mark_daily_notes_pushed(len(pushed_ids), error=error)

    if pushed_ids:
        try:
            ankiconnect_client.trigger_sync()
        except ankiconnect_client.AnkiConnectError:
            pass  # AnkiWeb sync is a bonus, not required for the push itself


_CATCH_UP_THRESHOLD_SECONDS = 20 * 3600  # ~20 hours


def catch_up_daily_notes_if_overdue() -> None:
    """Startup safety net for the scheduled Daily Notes job: a laptop that
    was asleep (or the server wasn't running) through the scheduled trigger
    time means that day's run may never have fired at all. Rather than
    waiting for tomorrow's occurrence, check on every startup -- which for
    a personal app that gets restarted often is itself a frequent, reliable
    opportunity to catch up -- and run immediately if it's been long enough
    since the last run and there's actually new text to card."""
    import time as _time

    notes = store.get_daily_notes()
    if notes.last_run_at is not None and (_time.time() - notes.last_run_at) < _CATCH_UP_THRESHOLD_SECONDS:
        return
    if not notes.text[notes.processed_length :].strip():
        return  # nothing new to card, no point running
    process_daily_notes()


def process_daily_notes() -> List[CardDraft]:
    """Cards only the text appended to the Daily Notes page since the last
    run (tracked via a character-offset checkpoint), so re-running never
    re-cards content that's already been turned into cards."""
    notes = store.get_daily_notes()
    new_content = notes.text[notes.processed_length :]
    # Compute the checkpoint from what we actually read, not by re-reading
    # notes.text later -- store.get_daily_notes() returns a live reference,
    # so a concurrent edit could otherwise make us mark newly-typed text as
    # already processed before it was ever sent to Claude.
    checkpoint = notes.processed_length + len(new_content)

    if not new_content.strip():
        store.mark_daily_notes_processed(checkpoint, 0)
        return []

    note_lines = [line.strip() for line in new_content.splitlines() if line.strip()]
    line_count = len(note_lines) or 1

    try:
        raw_cards = claude_client.generate_cards(
            context_text=f"== Daily notes (new since last run) ==\n{new_content}",
            card_type=CardType.basic,
            subject_hint=None,
            instructions=(
                "These are informal notes jotted down throughout the day, one line per "
                f"distinct note ({line_count} line(s) of new content below), possibly on "
                "unrelated topics. Produce ONE card per line as the default -- the total "
                "card count should track the number of lines, not exceed it. Only make an "
                "exception (two cards from a single line) if that line genuinely contains "
                "two separate, independently-testable critical facts, and in that case "
                "skip a card for a less noteworthy line elsewhere so the total stays at or "
                "under the line count. Skip a line entirely only if it's too vague or "
                "personal to quiz."
            ),
            max_cards=line_count,
            auto_count=True,
            auto_count_cap=line_count,
        )
    except Exception as exc:  # noqa: BLE001 - record failure, don't crash the scheduler
        store.mark_daily_notes_processed(notes.processed_length, 0, error=str(exc))
        raise

    deck = store.get_deck_name()
    cards = []
    for raw in raw_cards:
        tags = [t.strip() for t in raw.get("tags", []) if t.strip()]
        if "Daily Notes" not in tags:
            tags = ["Daily Notes"] + tags
        cards.append(
            CardDraft(
                card_type=CardType.basic,
                question=_render_question_html(raw.get("question", "")),
                answer=raw.get("answer", "").strip(),
                explanation=_render_explanation(raw.get("explanation_points", [])),
                tags=_apply_tag_root(tags, deck),
                deck=deck,
                source_ids=[],
            )
        )

    store.add_cards(cards)
    store.mark_daily_notes_processed(checkpoint, len(cards), questions=[c.question for c in cards])
    push_pending_daily_notes_cards()
    return cards
