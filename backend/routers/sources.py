import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from .. import config
from ..models import Source, SourceStatus, SourceType, new_id
from ..services.generator import process_source
from ..storage import store

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _guess_source_type(filename: str, content_type: str) -> SourceType:
    content_type = content_type or mimetypes.guess_type(filename)[0] or ""
    if content_type.startswith("image/"):
        return SourceType.image
    if content_type.startswith("audio/"):
        return SourceType.audio
    if content_type.startswith("video/"):
        return SourceType.video
    raise HTTPException(400, f"Unsupported file type: {content_type or filename}")


@router.get("")
def list_sources():
    return store.list_sources()


@router.post("/text")
def add_text_source(name: str = Form(...), text: str = Form(...)):
    source = Source(type=SourceType.text, name=name, raw_text=text)
    store.add_source(source)
    process_source(source)  # trivial/instant for plain text
    return store.get_source(source.id)


@router.post("/upload")
def upload_source(file: UploadFile = File(...)):
    source_type = _guess_source_type(file.filename, file.content_type)
    suffix = Path(file.filename).suffix
    stored_filename = f"{new_id('upload')}{suffix}"
    dest = config.UPLOAD_DIR / stored_filename

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    source = Source(
        type=source_type,
        name=file.filename,
        stored_filename=stored_filename,
    )
    store.add_source(source)
    return source


@router.post("/{source_id}/process")
def process_source_endpoint(source_id: str, background_tasks: BackgroundTasks):
    source = store.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if source.status == SourceStatus.processing:
        return source
    background_tasks.add_task(process_source, source)
    source.status = SourceStatus.processing
    store.update_source(source)
    return source


@router.get("/{source_id}")
def get_source(source_id: str):
    source = store.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.delete("/{source_id}")
def delete_source(source_id: str):
    store.delete_source(source_id)
    return {"ok": True}
