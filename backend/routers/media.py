from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import config
from ..storage import store

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("")
def list_media():
    return store.list_media()


@router.get("/{media_id}/file")
def get_media_file(media_id: str):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    path = config.MEDIA_DIR / media.filename
    if not path.exists():
        raise HTTPException(404, "Media file missing on disk")
    return FileResponse(path, media_type=media.mime_type)
