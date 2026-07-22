"""Orchestrates the pipeline: raw Source -> extracted text/media -> Claude ->
CardDraft objects. This is the only module that talks to both the storage
layer and the transcription/video/claude_client services."""
import html
import shutil
from pathlib import Path
from typing import List, Optional

from .. import config
from ..models import CardDraft, MediaItem, MediaKind, Source, SourceStatus, SourceType
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
            caption = claude_client.caption_image(path)
            media_filename = f"{source.id}_{source.stored_filename}"
            shutil.copy(path, config.MEDIA_DIR / media_filename)
            media = MediaItem(
                filename=media_filename,
                mime_type=_guess_mime(path),
                kind=MediaKind.uploaded_image,
                source_id=source.id,
                caption=caption,
            )
            store.add_media(media)
            source.media_ids = [media.id]
            source.extracted_text = caption

        elif source.type == SourceType.audio:
            path = config.UPLOAD_DIR / source.stored_filename
            source.extracted_text = transcription.transcribe(path)

        elif source.type == SourceType.video:
            path = config.UPLOAD_DIR / source.stored_filename
            audio_path = video.extract_audio(path, config.UPLOAD_DIR)
            transcript = transcription.transcribe(audio_path)

            frames = video.extract_keyframes(path, config.MEDIA_DIR)
            media_ids = []
            for frame_path, timestamp in frames:
                caption = claude_client.caption_image(frame_path)
                media = MediaItem(
                    filename=frame_path.name,
                    mime_type="image/jpeg",
                    kind=MediaKind.video_frame,
                    source_id=source.id,
                    timestamp_seconds=timestamp,
                    caption=caption,
                )
                store.add_media(media)
                media_ids.append(media.id)

            source.media_ids = media_ids
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
    all_media_ids = []
    for s in sources:
        header = f"== Source: {s.name} ({s.type.value}) =="
        context_chunks.append(f"{header}\n{s.extracted_text or ''}")
        all_media_ids.extend(s.media_ids)

    media_manifest = []
    for mid in all_media_ids:
        m = store.get_media(mid)
        if m:
            media_manifest.append({"id": m.id, "caption": m.caption or ""})

    raw_cards = claude_client.generate_cards(
        context_text="\n\n".join(context_chunks),
        media_manifest=media_manifest,
        subject_hint=subject_hint,
        instructions=instructions,
        max_cards=max_cards,
    )

    known_media_ids = {m["id"] for m in media_manifest}
    cards = []
    for raw in raw_cards:
        media_ids = [m for m in raw.get("media_ids", []) if m in known_media_ids]
        cards.append(
            CardDraft(
                question=raw.get("question", "").strip(),
                answer=raw.get("answer", "").strip(),
                explanation=_render_explanation(raw.get("explanation_points", [])),
                tags=[t.strip() for t in raw.get("tags", []) if t.strip()],
                media_ids=media_ids,
                deck=deck,
                source_ids=source_ids,
            )
        )

    store.add_cards(cards)
    return cards
