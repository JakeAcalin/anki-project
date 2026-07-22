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
   (a sentence with a `{{c1::blanked-out::hint}}` phrase — always includes a
   hint, so the blank is still answerable without the rest of the source
   material in front of you) as the card type, then Claude reads the
   processed source material and writes a set of atomic, text-only
   flashcards, respecting the max-cards limit exactly (not just as a
   suggestion), plus hierarchical tags. If any source has
   student-highlighted text, the number of cards is chosen automatically —
   one per highlighted concept — instead of using the manual max-cards
   setting. Cards never embed the original photo/keyframe — that keeps decks
   small and fast to sync, and pushes Claude to describe figures/graphs in
   words instead of relying on a (often low-quality) source image.
4. **Review & edit** — every field is editable in the browser before export:
   question/answer or cloze text, explanation, tags, deck, and inclusion. A
   live preview shows exactly how the card will render in Anki.
5. **Export** — download a standard `.apkg` file, or **Push to Anki** directly
   (see below).

Everything you've built (sources, media, cards) is saved server-side and
reloads automatically — nothing lives only in the browser tab. Switch to the
**Library** tab any time to browse everything you've generated as a
readable, wiki-style reference: a sidebar tree of your hierarchical tags on
the left, and on the right, every card under the selected topic rendered as
an article (question/cloze sentence, answer, and the full explanation),
searchable by keyword. This is a read/reference view, separate from the
Create tab's editable card list.

## Pushing directly into Anki (AnkiConnect)

Instead of exporting a file and importing it by hand, **Push to Anki** sends
cards straight into a running Anki desktop app via
[AnkiConnect](https://foosoft.net/projects/anki-connect/), a free Anki
add-on. This only works when:

- This app's backend is running on the **same computer** as Anki desktop
  (AnkiConnect only listens on `127.0.0.1`, so a remotely-hosted backend
  can't reach it — this is one more reason self-hosting on your own machine,
  see below, is the right setup for this feature).
- Anki desktop is open, with the AnkiConnect add-on installed (`Tools →
  Add-ons → Get Add-ons…`, code `2055492159`).

Setup is one-time: install the add-on, restart Anki, and the topbar's
**AnkiConnect** pill turns green whenever Anki is open. Push is idempotent —
editing a card here and pushing again updates the same Anki note (matched
internally by a hidden ID field) instead of creating a duplicate. After
pushing, it also triggers Anki's normal **Sync**, so if you're logged into
AnkiWeb in the desktop app, the new/updated cards flow to your phone and
AnkiWeb the same way a manual sync would.

**What this can't do:** there's no public AnkiWeb API, so nothing can push
cards into your AnkiWeb account directly without Anki desktop being open at
some point to relay them — "log into AnkiWeb and cards just appear" isn't
possible with any tool, not just this one.

**After a successful push**, the pushed cards and the sources that fed them
clear out of the Create tab automatically — the workspace resets so you can
start the next batch without old material cluttering the view. Nothing is
actually deleted from the cards themselves: they're archived (not shown in
Create, excluded from future exports/pushes) but remain fully visible and
searchable in the **Library** tab. Cards that fail to push are left alone
in Create so you can fix and retry them.

## Daily Notes

A fourth tab for a different workflow: instead of uploading discrete
sources, keep one running scratchpad you add a line or two to throughout
the day (e.g. from your phone, at work). Once a day, at a fixed time
(`DAILY_NOTES_CARD_TIME` in `.env`, default `23:59` server time), the app
automatically cards **only the text added since the last run** — it tracks
a checkpoint so nothing gets carded twice and nothing requires you to press
a button. Generated cards are tagged `Daily Notes` (plus whatever subject
tags Claude naturally assigns) so they're easy to find in the Library view
alongside everything else.

## Architecture

```
backend/
  main.py              FastAPI app + static file serving
  config.py             env-driven configuration
  scheduler.py           daily background job for Daily Notes card generation
  models.py              Source / MediaItem / CardDraft / DailyNotes / Project schemas
  storage.py             JSON-file-backed store (single-user, local app)
  services/
    transcription.py     local Whisper speech-to-text
    video.py               ffmpeg audio extraction + keyframe sampling
    claude_client.py       Claude vision captioning + structured card generation
    generator.py            orchestrates source processing -> card generation
    anki_export.py          genanki .apkg builder (custom note models, CSS)
    ankiconnect_client.py    pushes/updates cards in a local running Anki desktop
  routers/                 sources / media / generate / cards / export / project /
                            anki-connect / daily-notes
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

## Using it from your phone

### Self-host + Tailscale (recommended: free, and required for AnkiConnect)

Run the app on a computer you already own — this costs nothing, and it's
the *only* setup where **Push to Anki** (AnkiConnect) works at all, since
AnkiConnect only listens on `127.0.0.1` on whatever machine Anki desktop is
running on. [Tailscale](https://tailscale.com) (free for personal use) gives
your phone a secure, private route to that computer without exposing
anything to the public internet or fiddling with router port-forwarding.

1. **Install Tailscale** on the computer that will run this app, and on your
   phone (from [tailscale.com/download](https://tailscale.com/download)).
   Sign into the same account on both — they now share a private network.
2. **Set two things in `.env`** on the host computer:
   ```
   ANKI_APP_HOST=0.0.0.0
   APP_USERNAME=pick-a-username
   APP_PASSWORD=pick-a-strong-password
   ```
   `ANKI_APP_HOST=0.0.0.0` makes the server reachable from other devices
   (not just `localhost`); the username/password matter because `0.0.0.0`
   also means anything on your home Wi-Fi could technically reach it — auth
   keeps it locked to you. (Tailscale itself also only lets *your own*
   authorized devices onto the tailnet in the first place, so this is a
   second layer, not your only protection.)
3. **Run it**: `./run.sh`. Leave this running — the computer needs to stay
   on and awake for your phone to reach it (disable sleep, or just use a
   machine that's normally on anyway).
4. **Find the host's Tailscale address**: run `tailscale ip -4` on the host
   computer.
5. **From your phone**, open `http://<that-ip>:8000` in a browser and log in
   with the username/password from step 2.
6. **Add it to your home screen** for a real app-like icon and a full-screen
   launch (no browser address bar): the app ships its own icon and manifest.
   - **iOS Safari**: Share button → **Add to Home Screen**.
   - **Android Chrome**: ⋮ menu → **Add to Home screen** (or **Install app**
     if Chrome offers it).

Since Anki desktop needs to be open on that same computer for **Push to
Anki** to work, this setup naturally puts everything in one place: the app,
Anki desktop, and (via Tailscale) your phone's access to both.

To keep it running after you close the terminal or reboot, wrap `./run.sh`
in whatever your OS uses for background services — `nohup ./run.sh &` or a
`tmux`/`screen` session is the quick version; a proper `systemd --user`
unit (Linux) or `launchd` agent (macOS) is the durable version if you want
it to survive reboots unattended.

### Cloud hosting (Railway, Render, Fly.io, a VPS)

Still an option if you'd rather not keep a computer on, or want a URL
reachable without Tailscale — the app is a normal Docker container, so it
runs on any host that builds from the included `Dockerfile`. **Trade-off:
AnkiConnect can't work this way** (it can't reach `127.0.0.1` on your
computer from someone else's server), so a cloud deployment is
export-only (`.apkg` download/import). Steps below use **Railway** as an
example since it needs no CLI, just a browser — Render and Fly.io work the
same way (point them at the `Dockerfile`, set the same env vars, attach a
persistent volume at `/app/data`).

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → pick this repo. Railway detects the `Dockerfile` automatically.
3. Open the service's **Variables** tab and add:
   - `ANTHROPIC_API_KEY`
   - `APP_USERNAME`, `APP_PASSWORD`
   - `WHISPER_MODEL_SIZE=tiny` (recommended on small/hobby plans — `small`/`medium` need more RAM than free tiers usually give)
4. Open the **Volumes** tab and attach a volume mounted at `/app/data`. Without this, uploads, generated cards, and the downloaded Whisper model all disappear on every redeploy/restart.
5. Under **Settings → Networking**, click **Generate Domain** to get a public `https://...up.railway.app` URL.
6. Open that URL from your phone's browser, log in with the username/password from step 3, and use it like the local version.

Note this is a paid tier on Railway once you're past any trial credit —
Whisper transcription alone needs more RAM/CPU than free tiers typically
allow. If cost is the concern, self-hosting above is the better default.
