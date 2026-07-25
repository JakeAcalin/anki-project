import json
import threading
from typing import List, Optional

import time

from . import config
from .models import CardDraft, DailyNotes, MediaItem, Project, ReferenceNote, Source


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

    # -- reference notes --
    def add_reference_notes(self, notes: List[ReferenceNote]) -> List[ReferenceNote]:
        with self._lock:
            self._project.reference_notes.extend(notes)
            self._save()
            return notes

    def list_reference_notes(self) -> List[ReferenceNote]:
        with self._lock:
            return list(self._project.reference_notes)

    def get_reference_note(self, note_id: str) -> Optional[ReferenceNote]:
        with self._lock:
            return next((n for n in self._project.reference_notes if n.id == note_id), None)

    def update_reference_note(self, note: ReferenceNote) -> ReferenceNote:
        with self._lock:
            for i, n in enumerate(self._project.reference_notes):
                if n.id == note.id:
                    self._project.reference_notes[i] = note
                    break
            self._save()
            return note

    def delete_reference_note(self, note_id: str) -> None:
        with self._lock:
            self._project.reference_notes = [
                n for n in self._project.reference_notes if n.id != note_id
            ]
            self._save()

    # -- project-wide --
    def all_tags(self) -> List[str]:
        with self._lock:
            tags = set()
            for c in self._project.cards:
                tags.update(c.tags)
            for n in self._project.reference_notes:
                tags.update(n.tags)
            return sorted(tags)

    def set_deck_name(self, name: str) -> None:
        with self._lock:
            self._project.deck_name = name
            self._save()

    def get_deck_name(self) -> str:
        with self._lock:
            return self._project.deck_name

    def is_tag_root_migrated(self) -> bool:
        with self._lock:
            return self._project.migrated_tag_root

    def mark_tag_root_migrated(self) -> None:
        with self._lock:
            self._project.migrated_tag_root = True
            self._save()

    def is_tag_root_removed_migrated(self) -> bool:
        with self._lock:
            return self._project.migrated_tag_root_removed

    def mark_tag_root_removed_migrated(self) -> None:
        with self._lock:
            self._project.migrated_tag_root_removed = True
            self._save()

    def is_tag_root_readded_migrated(self) -> bool:
        with self._lock:
            return self._project.migrated_tag_root_readded

    def mark_tag_root_readded_migrated(self) -> None:
        with self._lock:
            self._project.migrated_tag_root_readded = True
            self._save()

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

    def claim_daily_notes_text(self) -> str:
        """Atomically take the un-carded text out of the box and return it.

        Claiming has to happen *before* the model call, not after it. The
        call takes tens of seconds, and anything that starts a second run in
        that window -- a double-tapped Run Now, the scheduled job landing on
        top of the startup catch-up -- would otherwise read the very same
        text and card it all over again, which is exactly how two versions
        of one note end up in the deck.

        Returns "" when there's nothing new, which is also the signal to a
        second caller that the first one already took the work.
        """
        with self._lock:
            notes = self._project.daily_notes
            claimed = notes.text[notes.processed_length :]
            if not claimed.strip():
                return ""
            # Everything up to here is now this run's responsibility; what's
            # left in the box is only whatever gets typed from now on.
            notes.text = notes.text[notes.processed_length + len(claimed) :]
            notes.processed_length = 0
            self._save()
            return claimed

    def restore_daily_notes_text(self, claimed: str) -> None:
        """Put claimed text back after a failed run, so it isn't lost."""
        with self._lock:
            notes = self._project.daily_notes
            notes.text = claimed + notes.text
            notes.processed_length = 0
            self._save()

    def record_daily_notes_run(
        self,
        card_count: int,
        error: Optional[str] = None,
        questions: Optional[List[str]] = None,
        skipped_duplicates: int = 0,
    ) -> DailyNotes:
        """Record the outcome of a run. The text itself was already removed
        from the box by `claim_daily_notes_text` when the run started."""
        with self._lock:
            notes = self._project.daily_notes
            notes.last_run_at = time.time()
            notes.last_run_card_count = card_count
            notes.last_run_error = error
            notes.last_run_skipped_duplicates = skipped_duplicates
            if questions is not None:
                notes.last_run_questions = questions
            self._save()
            return notes

    def mark_daily_notes_pushed(self, pushed_count: int, error: Optional[str] = None) -> DailyNotes:
        with self._lock:
            notes = self._project.daily_notes
            notes.last_push_at = time.time()
            notes.last_push_count = pushed_count
            notes.last_push_error = error
            self._save()
            return notes

    # -- truelearn notes import --
    def get_truelearn_seen_ids(self) -> set:
        with self._lock:
            return set(self._project.truelearn_seen_ids)

    def add_truelearn_seen_ids(self, ids) -> None:
        with self._lock:
            seen = set(self._project.truelearn_seen_ids)
            seen.update(ids)
            self._project.truelearn_seen_ids = sorted(seen)
            self._save()


store = Store()
