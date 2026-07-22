# Anki Card Media Generator

Turn text, images, audio, and video into Anki flashcards. Each card gets a
short front-side question and a detailed, AI-written back-side explanation,
organized with hierarchical tags (`Subject::Topic::Detail`) and subdecks
(`Subject::Topic`).

## How it works

1. **Add sources** — paste text, or upload images, audio, or video files.
2. **Process** — each source is turned into plain text:
   - Text stays as-is.
   - Images are captioned by Claude's vision model — that caption becomes
     the source's text content (e.g. a photo of a textbook figure becomes a
     written description of what it shows). Claude also separately flags any
     text a *student* has marked with a highlighter pen (as opposed to the
     textbook's own bold/italic/caption emphasis).
   - Audio is transcribed locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no cloud, no API key).
   - Video has its audio track transcribed the same way, plus keyframes are
     sampled and captioned so relevant visual moments (and any highlighted
     text visible in them) inform card generation.
3. **Generate** — choose **Basic** (question/answer) or **Cloze deletion**
   (a sentence with a `{{c1::blanked-out}}` phrase) as the card type, then
   Claude reads the processed source material and writes a set of atomic,
   text-only flashcards, plus hierarchical tags. If any source has
   student-highlighted text, the number of cards is chosen automatically —
   one per highlighted concept — instead of using the manual max-cards
   setting. Cards never embed the original photo/keyframe — that keeps decks
   small and fast to sync, and pushes Claude to describe figures/graphs in
   words instead of relying on a (often low-quality) source image.
4. **Review & edit** — every field is editable in the browser before export:
   question/answer or cloze text, explanation, tags, deck, and inclusion. A
   live preview shows exactly how the card will render in Anki.
5. **Export** — download a standard `.apkg` file and import it into Anki.

Everything you've built (sources, media, cards) is saved server-side and
reloads automatically — nothing lives only in the browser tab. Switch to the
**Library** tab any time to browse everything you've generated as a
readable, wiki-style reference: a sidebar tree of your hierarchical tags on
the left, and on the right, every card under the selected topic rendered as
an article (question/cloze sentence, answer, and the full explanation),
searchable by keyword. This is a read/reference view, separate from the
Create tab's editable card list.

## Architecture

```
backend/
  main.py              FastAPI app + static file serving
  config.py             env-driven configuration
  models.py              Source / MediaItem / CardDraft / Project schemas
  storage.py             JSON-file-backed store (single-user, local app)
  services/
    transcription.py     local Whisper speech-to-text
    video.py               ffmpeg audio extraction + keyframe sampling
    claude_client.py       Claude vision captioning + structured card generation
    generator.py            orchestrates source processing -> card generation
    anki_export.py          genanki .apkg builder (custom note model, CSS)
  routers/                 sources / media / generate / cards / export / project
frontend/
  index.html, style.css, app.js   no-build vanilla JS single-page UI
```

Hierarchical tags rely on Anki's native `::` nesting convention, so tags like
`Biology::CellBiology::Photosynthesis` show up as a nested tree in Anki's
tag sidebar. The same convention is used for deck names to create subdecks.

## Setup

Prerequisites: Python 3.10+, [ffmpeg](https://ffmpeg.org/) on your `PATH`.

```bash
./run.sh
```

This creates a virtualenv, installs dependencies, copies `.env.example` to
`.env` on first run, and starts the server at http://127.0.0.1:8000.

Open that URL in your browser to use the app.

### Enabling AI features

Add your key to `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Without a key, you can still upload sources and transcribe audio/video
locally, but image captioning and card generation require Claude.

### Whisper model

The first time you process audio or video, `faster-whisper` downloads model
weights (default size: `small`, a few hundred MB). Tune size/speed via
`WHISPER_MODEL_SIZE` in `.env` (`tiny`, `base`, `small`, `medium`, `large-v3`).

## Notes

- All project state (sources, media, cards) is stored locally in `data/`,
  which is gitignored — nothing leaves your machine except calls to the
  Claude API for captioning/generation.
- The exported `.apkg` uses a custom note type with a styled answer side:
  the short answer, then a highlighted "detailed explanation" block, then
  any attached images.

## Deploying it (so you can use it from your phone or any browser)

The app is a normal Docker container, so it runs on any host that builds
from a `Dockerfile` — Railway, Render, Fly.io, a VPS, etc. Steps below use
**Railway** since it needs no CLI, just a browser.

### 1. Protect it before making it public

Anyone who can reach the URL can spend your `ANTHROPIC_API_KEY` credits and
see your uploaded media, since there's no login by default. Set these two
env vars on the host (not in git) to require a login:

```
APP_USERNAME=pick-a-username
APP_PASSWORD=pick-a-strong-password
```

Leaving either unset disables auth entirely — that's fine for local-only
use, but always set both for anything public.

### 2. Deploy on Railway

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → pick this repo. Railway detects the `Dockerfile` automatically.
3. Open the service's **Variables** tab and add:
   - `ANTHROPIC_API_KEY`
   - `APP_USERNAME`, `APP_PASSWORD`
   - `WHISPER_MODEL_SIZE=tiny` (recommended on small/hobby plans — `small`/`medium` need more RAM than free tiers usually give)
4. Open the **Volumes** tab and attach a volume mounted at `/app/data`. Without this, uploads, generated cards, and the downloaded Whisper model all disappear on every redeploy/restart.
5. Under **Settings → Networking**, click **Generate Domain** to get a public `https://...up.railway.app` URL.
6. Open that URL from your phone's browser, log in with the username/password from step 1, and use it like the local version.

Render and Fly.io work the same way (point them at the `Dockerfile`, set the
same env vars, attach a persistent disk/volume at `/app/data`) if you prefer
either of those instead.

### Cost/behavior notes for a hosted deployment

- Whisper transcription now runs on the host's CPU instead of yours — slower
  and, on paid plans, part of what you're billed for. `tiny`/`base` models
  are noticeably faster on constrained hardware than `small` and up.
  large videos will take longer to transcribe than on a beefy laptop.
- The Anthropic API calls (captioning, card generation) work identically
  wherever the app runs — you're billed by API usage either way, not by host.
