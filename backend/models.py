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
    created_at: float = Field(default_factory=time.time)


class CardDraft(BaseModel):
    id: str = Field(default_factory=lambda: new_id("card"))
    question: str
    answer: str
    explanation: str = ""
    tags: List[str] = Field(default_factory=list)
    media_ids: List[str] = Field(default_factory=list)
    deck: str = "Default"
    source_ids: List[str] = Field(default_factory=list)
    included: bool = True
    created_at: float = Field(default_factory=time.time)


class Project(BaseModel):
    sources: List[Source] = Field(default_factory=list)
    media: List[MediaItem] = Field(default_factory=list)
    cards: List[CardDraft] = Field(default_factory=list)
    deck_name: str = "My Deck"


class GenerateRequest(BaseModel):
    source_ids: List[str]
    deck: str = "My Deck"
    subject_hint: Optional[str] = None
    instructions: Optional[str] = None
    max_cards: int = 20


class ExportRequest(BaseModel):
    card_ids: Optional[List[str]] = None
    deck_name: Optional[str] = None
    filename: Optional[str] = None
