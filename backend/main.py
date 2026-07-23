from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import migrations, scheduler
from .auth import BasicAuthMiddleware
from .routers import ankiconnect, cards, daily_notes, export, generate, media, project, sources

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """The frontend is a handful of static files (index.html, app.js,
    style.css) that get overwritten in place on every deploy/update. Without
    this, browsers can silently keep serving an old cached copy after a
    `git pull` + restart, which looks like the update didn't take effect."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app = FastAPI(title="Anki Card Media Generator")

app.add_middleware(BasicAuthMiddleware)
app.add_middleware(NoCacheStaticMiddleware)

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
    migrations.run_migrations()
    scheduler.start()


@app.on_event("shutdown")
def _on_shutdown():
    scheduler.stop()


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
