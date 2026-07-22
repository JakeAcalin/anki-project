from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from . import scheduler
from .auth import BasicAuthMiddleware
from .routers import ankiconnect, cards, daily_notes, export, generate, media, project, sources

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Anki Card Media Generator")

app.add_middleware(BasicAuthMiddleware)

app.include_router(sources.router)
app.include_router(media.router)
app.include_router(generate.router)
app.include_router(cards.router)
app.include_router(export.router)
app.include_router(project.router)
app.include_router(ankiconnect.router)
app.include_router(daily_notes.router)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.on_event("startup")
def _on_startup():
    scheduler.start()


@app.on_event("shutdown")
def _on_shutdown():
    scheduler.stop()


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
