from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routers import cards, export, generate, media, project, sources

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Anki Card Media Generator")

app.include_router(sources.router)
app.include_router(media.router)
app.include_router(generate.router)
app.include_router(cards.router)
app.include_router(export.router)
app.include_router(project.router)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
