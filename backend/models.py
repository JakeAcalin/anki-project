import time
import uuid
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class SourceType(str, Enum):
    text = "text"
    image = "image"
    audio = "audio"
    video = "video"


class SourceStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    error = "error"


class MediaKind(str, Enum):
    uploaded_image = "uploaded_image"
    video_frame = "video_frame"


class CardType(str, Enum):
    basic = "basic"
    cloze = "cloze"


class MediaItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("media"))
    filename: str
    mime_type: str
    kind: MediaKind
    source_id: Optional[str] = None
    timestamp_seconds: Optional[float] = None
    caption: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


class Source(BaseModel):
    id: str = Field(default_factory=lambda: new_id("src"))
    type: SourceType
    name: str
    status: SourceStatus = SourceStatus.pending
    error: Optional[str] = None
    raw_text: Optional[str] = None
    extracted_text: Optional[str] = None
    stored_filename: Optional[str] = None
    media_ids: List[str] = Field(default_factory=list)
    highlighted_excerpts: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class CardDraft(BaseModel):
    id: str = Field(default_factory=lambda: new_id("card"))
    card_type: CardType = CardType.basic
    question: str = ""
    answer: str = ""
    cloze_text: str = ""
    explanation: str = ""
    tags: List[str] = Field(default_factory=list)
    media_ids: List[str] = Field(default_factory=list)
    deck: str = "Default"
    source_ids: List[str] = Field(default_factory=list)
    included: bool = True
    archived: bool = False
    anki_note_id: Optional[int] = None
    created_at: float = Field(default_factory=time.time)


class DailyNotes(BaseModel):
    text: str = ""
    processed_length: int = 0
    last_run_at: Optional[float] = None
    last_run_card_count: int = 0
    last_run_error: Optional[str] = None
    last_push_at: Optional[float] = None
    last_push_count: int = 0
    last_push_error: Optional[str] = None


class Project(BaseModel):
    sources: List[Source] = Field(default_factory=list)
    media: List[MediaItem] = Field(default_factory=list)
    cards: List[CardDraft] = Field(default_factory=list)
    deck_name: str = "My Deck"
    daily_notes: DailyNotes = Field(default_factory=DailyNotes)
    migrated_tag_root: bool = False


class GenerateRequest(BaseModel):
    source_ids: List[str]
    deck: str = "My Deck"
    card_type: CardType = CardType.basic
    subject_hint: Optional[str] = None
    instructions: Optional[str] = None
    max_cards: int = 20


class ExportRequest(BaseModel):
    card_ids: Optional[List[str]] = None
    deck_name: Optional[str] = None
    filename: Optional[str] = None
