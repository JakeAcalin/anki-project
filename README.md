# Anki Card Media Generator

Turn text, images, audio, and video into Anki flashcards. Each card gets a
short front-side question and a detailed, AI-written back-side explanation
(text + images), organized with hierarchical tags (`Subject::Topic::Detail`)
and subdecks (`Subject::Topic`).

## How it works

1. **Add sources** — paste text, or upload images, audio, or video files.
2. **Process** — each source is turned into plain text:
   - Text stays as-is.
   - Images are captioned by Claude's vision model.
   - Audio is transcribed locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no cloud, no API key).
   - Video has its audio track transcribed the same way, plus keyframes are
     sampled and captioned so relevant frames can be attached to cards.
3. **Generate** — Claude reads the processed source material and writes a set
   of atomic flashcards: a question, a short answer, a detailed HTML
   explanation for the answer side, hierarchical tags, and (when relevant)
   an image to embed.
4. **Review & edit** — every field is editable in the browser before export:
   question, answer, explanation, tags, deck, and inclusion.
5. **Export** — download a standard `.apkg` file and import it into Anki.

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
