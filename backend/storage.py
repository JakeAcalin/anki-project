import json
import threading
from typing import List, Optional

import time

from . import config
from .models import CardDraft, DailyNotes, MediaItem, Project, Source


def _unlink_quiet(path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class Store:
    """Simple JSON-file-backed project store. Single-user, single-process app,
    so a process-wide lock around read-modify-write is sufficient."""

    def __init__(self, path=config.PROJECT_FILE):
        self._path = path
        self._lock = threading.RLock()
        self._project = self._load()

    def _load(self) -> Project:
        if self._path.exists():
            try:
                return Project.model_validate_json(self._path.read_text())
            except Exception:
                pass
        return Project()

    def _save(self) -> None:
        self._path.write_text(self._project.model_dump_json(indent=2))

    # -- sources --
    def add_source(self, source: Source) -> Source:
        with self._lock:
            self._project.sources.append(source)
            self._save()
            return source

    def get_source(self, source_id: str) -> Optional[Source]:
        with self._lock:
            return next((s for s in self._project.sources if s.id == source_id), None)

    def list_sources(self) -> List[Source]:
        with self._lock:
            return list(self._project.sources)

    def update_source(self, source: Source) -> Source:
        with self._lock:
            for i, s in enumerate(self._project.sources):
                if s.id == source.id:
                    self._project.sources[i] = source
                    break
            self._save()
            return source

    def delete_source(self, source_id: str) -> None:
        with self._lock:
            source = next((s for s in self._project.sources if s.id == source_id), None)
            if source is None:
                return
            orphaned_media = [m for m in self._project.media if m.source_id == source_id]

            self._project.sources = [s for s in self._project.sources if s.id != source_id]
            self._project.media = [m for m in self._project.media if m.source_id != source_id]
            self._save()

        # Best-effort disk cleanup outside the lock -- a leftover file here
        # is harmless clutter, not a correctness issue worth blocking on.
        if source.stored_filename:
            _unlink_quiet(config.UPLOAD_DIR / source.stored_filename)
        for media in orphaned_media:
            _unlink_quiet(config.MEDIA_DIR / media.filename)

    # -- media --
    def add_media(self, media: MediaItem) -> MediaItem:
        with self._lock:
            self._project.media.append(media)
            self._save()
            return media

    def get_media(self, media_id: str) -> Optional[MediaItem]:
        with self._lock:
            return next((m for m in self._project.media if m.id == media_id), None)

    def list_media(self) -> List[MediaItem]:
        with self._lock:
            return list(self._project.media)

    def update_media(self, media: MediaItem) -> MediaItem:
        with self._lock:
            for i, m in enumerate(self._project.media):
                if m.id == media.id:
                    self._project.media[i] = media
                    break
            self._save()
            return media

    # -- cards --
    def add_cards(self, cards: List[CardDraft]) -> List[CardDraft]:
        with self._lock:
            self._project.cards.extend(cards)
            self._save()
            return cards

    def list_cards(self) -> List[CardDraft]:
        with self._lock:
            return list(self._project.cards)

    def get_card(self, card_id: str) -> Optional[CardDraft]:
        with self._lock:
            return next((c for c in self._project.cards if c.id == card_id), None)

    def update_card(self, card: CardDraft) -> CardDraft:
        with self._lock:
            for i, c in enumerate(self._project.cards):
                if c.id == card.id:
                    self._project.cards[i] = card
                    break
            self._save()
            return card

    def delete_card(self, card_id: str) -> None:
        with self._lock:
            self._project.cards = [c for c in self._project.cards if c.id != card_id]
            self._save()

    # -- project-wide --
    def all_tags(self) -> List[str]:
        with self._lock:
            tags = set()
            for c in self._project.cards:
                tags.update(c.tags)
            return sorted(tags)

    def set_deck_name(self, name: str) -> None:
        with self._lock:
            self._project.deck_name = name
            self._save()

    def get_deck_name(self) -> str:
        with self._lock:
            return self._project.deck_name

    def reset(self) -> None:
        with self._lock:
            self._project = Project()
            self._save()

    # -- daily notes --
    def get_daily_notes(self) -> DailyNotes:
        with self._lock:
            return self._project.daily_notes

    def update_daily_notes_text(self, text: str) -> DailyNotes:
        with self._lock:
            self._project.daily_notes.text = text
            self._save()
            return self._project.daily_notes

    def mark_daily_notes_processed(
        self, processed_length: int, card_count: int, error: Optional[str] = None
    ) -> DailyNotes:
        with self._lock:
            notes = self._project.daily_notes
            notes.processed_length = processed_length
            notes.last_run_at = time.time()
            notes.last_run_card_count = card_count
            notes.last_run_error = error
            self._save()
            return notes


store = Store()
