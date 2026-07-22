"""Orchestrates the pipeline: raw Source -> extracted text/media -> Claude ->
CardDraft objects. This is the only module that talks to both the storage
layer and the transcription/video/claude_client services."""
import html
import shutil
from pathlib import Path
from typing import List, Optional

from .. import config
from ..models import CardDraft, CardType, MediaItem, MediaKind, Source, SourceStatus, SourceType
from ..storage import store
from . import claude_client, transcription, video


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


def _render_explanation(points: List[str]) -> str:
    """Build guaranteed-safe HTML from plain-text bullet points instead of
    trusting an LLM to hand-write valid HTML. Escaping here means a stray
    '<' or '&' in the model's text can never leak through as a broken tag
    or show up literally on the card."""
    items = []
    for p in points:
        if not isinstance(p, str):
            continue
        cleaned = p.strip().lstrip("-*•").strip()
        if cleaned:
            items.append(cleaned)
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


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

    auto_count = any(s.highlighted_excerpts for s in sources)

    raw_cards = claude_client.generate_cards(
        context_text="\n\n".join(context_chunks),
        card_type=card_type,
        subject_hint=subject_hint,
        instructions=instructions,
        max_cards=max_cards,
        auto_count=auto_count,
    )

    cards = []
    for raw in raw_cards:
        common = dict(
            card_type=card_type,
            explanation=_render_explanation(raw.get("explanation_points", [])),
            tags=[t.strip() for t in raw.get("tags", []) if t.strip()],
            deck=deck,
            source_ids=source_ids,
        )
        if card_type == CardType.basic:
            cards.append(
                CardDraft(
                    question=raw.get("question", "").strip(),
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
    return cards
