const state = {
  sources: [],
  media: [],
  cards: [],
  deckName: "My Deck",
  claudeConfigured: true,
  selectedSourceIds: new Set(),
  cardType: "basic",
  ankiConnectAvailable: false,
  dailyNotes: {
    text: "", processed_length: 0, last_run_at: null, last_run_card_count: 0, last_run_error: null,
    last_run_questions: [], last_push_at: null, last_push_count: 0, last_push_error: null,
  },
  dailyNotesCardTime: "23:59",
};

const libraryState = {
  selectedPath: null, // null = "All topics"
  search: "",
};

let pollHandle = null;
let dailyNotesSaveTimer = null;

// ---------- theme ----------

const THEME_KEY = "anki_app_theme";

function effectiveDarkTheme(stored) {
  if (stored === "dark") return true;
  if (stored === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(stored) {
  if (stored === "light" || stored === "dark") {
    document.documentElement.dataset.theme = stored;
  } else {
    delete document.documentElement.dataset.theme;
  }
  const btn = document.getElementById("themeToggleBtn");
  if (btn) btn.textContent = effectiveDarkTheme(stored) ? "🌙" : "☀️";
}

function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY));
  document.getElementById("themeToggleBtn").addEventListener("click", () => {
    const next = effectiveDarkTheme(localStorage.getItem(THEME_KEY)) ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

// ---------- API helpers ----------

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return res.json();
  return res;
}

function mediaUrl(mediaId) {
  return `/api/media/${mediaId}/file`;
}

// ---------- toast / banner ----------

function showToast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " error" : "");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), 3500);
}

function showBanner(message) {
  const el = document.getElementById("banner");
  el.textContent = message;
  el.classList.remove("hidden");
}

function hideBanner() {
  document.getElementById("banner").classList.add("hidden");
}

// ---------- data loading ----------

async function loadProject() {
  const data = await api("/api/project");
  state.sources = data.sources;
  state.media = data.media;
  state.cards = data.cards;
  state.deckName = data.deck_name;
  state.claudeConfigured = data.claude_configured;
  state.dailyNotes = data.daily_notes;
  state.dailyNotesCardTime = data.daily_notes_card_time;
  renderAll();
  manageServerPolling();
  refreshAnkiConnectStatus();
}

async function refreshAnkiConnectStatus() {
  try {
    const data = await api("/api/anki-connect/status");
    state.ankiConnectAvailable = data.available;
  } catch (_) {
    state.ankiConnectAvailable = false;
  }
  renderAnkiConnectStatus();
}

function renderAnkiConnectStatus() {
  const el = document.getElementById("ankiConnectStatus");
  if (state.ankiConnectAvailable) {
    el.textContent = "AnkiConnect: connected";
    el.className = "api-status ok";
  } else {
    el.textContent = "AnkiConnect: not running";
    el.className = "api-status neutral";
  }
}

function manageServerPolling() {
  const anyProcessing = state.sources.some((s) => s.status === "processing");
  if (anyProcessing && !pollHandle) {
    pollHandle = setInterval(async () => {
      const data = await api("/api/project");
      state.sources = data.sources;
      state.media = data.media;
      renderSources();
      renderSourceCheckboxes();
      if (!state.sources.some((s) => s.status === "processing")) {
        clearInterval(pollHandle);
        pollHandle = null;
      }
    }, 1500);
  }
}

// ---------- rendering ----------

function renderAll() {
  document.getElementById("deckNameInput").value = state.deckName;
  const statusEl = document.getElementById("apiStatus");
  if (state.claudeConfigured) {
    statusEl.textContent = "Claude API: connected";
    statusEl.className = "api-status ok";
    hideBanner();
  } else {
    statusEl.textContent = "Claude API: not configured";
    statusEl.className = "api-status bad";
    showBanner(
      "ANTHROPIC_API_KEY is not set on the server. Add it to your .env file and restart to enable AI captioning and card generation."
    );
  }
  renderSources();
  renderSourceCheckboxes();
  renderCards();
  renderTagCloud();
}

const STATUS_LABEL = { pending: "pending", processing: "processing…", done: "ready", error: "error" };

function renderSources() {
  const list = document.getElementById("sourceList");
  if (state.sources.length === 0) {
    list.innerHTML = `<li class="empty-state">No sources yet. Upload a file or paste text above.</li>`;
    return;
  }
  list.innerHTML = state.sources
    .map((s) => {
      const canProcess = s.status === "pending" || s.status === "error";
      return `
      <li class="source-item" data-id="${s.id}">
        <div class="source-item-top">
          <span class="source-name" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
          <span class="badge ${s.status}">${STATUS_LABEL[s.status]}</span>
        </div>
        <div class="source-actions">
          ${canProcess ? `<button class="link-btn" data-action="process">Process</button>` : ""}
          <button class="icon-btn" data-action="delete">Remove</button>
        </div>
        ${s.error ? `<div class="source-error">${escapeHtml(s.error)}</div>` : ""}
      </li>`;
    })
    .join("");
}

function renderSourceCheckboxes() {
  const el = document.getElementById("sourceCheckboxes");
  if (state.sources.length === 0) {
    el.innerHTML = `<div class="empty-state">Add sources first.</div>`;
    return;
  }
  el.innerHTML = state.sources
    .map((s) => {
      const disabled = s.status !== "done";
      const checked = state.selectedSourceIds.has(s.id) && !disabled;
      return `
      <label class="${disabled ? "disabled" : ""}">
        <input type="checkbox" data-source-id="${s.id}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
        ${escapeHtml(s.name)} <span class="badge ${s.status}">${STATUS_LABEL[s.status]}</span>
      </label>`;
    })
    .join("");
}

function renderTagCloud() {
  const el = document.getElementById("tagCloud");
  const tags = new Set();
  // Same visibility rule as the card list below it: a tag cloud full of
  // tags from cards you can't even see (already pushed & archived) reads
  // as leftover clutter, not a "fresh workspace."
  state.cards.filter((c) => !c.archived).forEach((c) => c.tags.forEach((t) => tags.add(t)));
  if (tags.size === 0) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = [...tags]
    .sort()
    .map((t) => `<span class="tag-chip" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`)
    .join("");
}

function renderClozePreview(text) {
  const escaped = escapeHtml(text || "");
  return escaped.replace(
    /\{\{c\d+::(.*?)(?:::.*?)?\}\}/g,
    (_match, inner) => `<span class="cloze-blank">${inner}</span>`
  );
}


function renderCards() {
  const list = document.getElementById("cardList");
  const visibleCards = state.cards.filter((c) => !c.archived);
  // The review/edit section is just clutter before there's anything to
  // review, so keep it out of the way until the first card exists.
  document.getElementById("reviewSection").classList.toggle("hidden", visibleCards.length === 0);
  if (visibleCards.length === 0) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = visibleCards
    .map((c) => {
      const images = c.media_ids
        .map((mid) => `<img src="${mediaUrl(mid)}" alt="" />`)
        .join("");
      const isCloze = c.card_type === "cloze";
      const frontFields = isCloze
        ? `
            <div class="card-field-label">Cloze text</div>
            <p class="field-hint" style="margin: -4px 0 2px 0;">Wrap the hidden part in <code>{{c1::like this}}</code>.</p>
            <textarea data-field="cloze_text">${escapeHtml(c.cloze_text)}</textarea>
            <div class="card-field-label">Preview</div>
            <div class="explanation-preview cloze-preview" data-preview="cloze_text">${renderClozePreview(c.cloze_text)}</div>`
        : `
            <div class="card-field-label">Question (edit as HTML source)</div>
            <p class="field-hint" style="margin: -4px 0 2px 0;">Wrap key words in <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, or <code>&lt;u&gt;</code> tags to emphasize them.</p>
            <textarea data-field="question">${escapeHtml(c.question)}</textarea>
            <div class="card-field-label">Preview</div>
            <div class="question-preview" data-preview="question">${c.question}</div>
            <div class="card-field-label">Answer</div>
            <textarea data-field="answer">${escapeHtml(c.answer)}</textarea>`;

      return `
      <div class="card-item ${c.included ? "" : "excluded"}" data-id="${c.id}" data-card-type="${c.card_type}">
        <div class="card-item-top">
          <input type="checkbox" data-field="included" ${c.included ? "checked" : ""} title="Include in export" />
          <div class="card-fields">
            <span class="card-type-pill">${isCloze ? "Cloze" : "Basic"}</span>
            ${frontFields}
            <div class="card-field-label">Explanation (answer-side detail — edit as HTML source)</div>
            <textarea class="explanation" data-field="explanation">${escapeHtml(c.explanation)}</textarea>
            <div class="card-field-label">Preview (what Anki will actually show)</div>
            <div class="explanation-preview" data-preview="explanation">${c.explanation}</div>
            ${images ? `<div class="card-images">${images}</div>` : ""}
            <div class="card-tags-row">
              <span class="card-field-label">Tags</span>
              <input type="text" data-field="tags" value="${escapeHtml(c.tags.join(", "))}" placeholder="Topic::Subtopic, OtherTag" />
            </div>
            <div class="card-deck-row">
              Deck: <input type="text" data-field="deck" value="${escapeHtml(c.deck)}" />
              <button class="icon-btn" data-action="delete">Delete card</button>
            </div>
          </div>
        </div>
      </div>`;
    })
    .join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------- Library view ----------

function buildTagTree(cards) {
  const root = {};
  for (const c of cards) {
    for (const tag of c.tags) {
      const parts = tag.split("::").map((p) => p.trim()).filter(Boolean);
      let node = root;
      let path = [];
      for (const part of parts) {
        path.push(part);
        if (!node[part]) node[part] = { children: {}, path: path.join("::") };
        node = node[part].children;
      }
    }
  }
  return root;
}

function cardsUnderPath(cards, path) {
  if (!path) return cards;
  return cards.filter((c) => c.tags.some((t) => t === path || t.startsWith(path + "::")));
}

function renderTopicTree(node, cards) {
  const keys = Object.keys(node).sort((a, b) => a.localeCompare(b));
  if (keys.length === 0) return "";
  return (
    '<ul class="topic-tree-list">' +
    keys
      .map((key) => {
        const entry = node[key];
        const count = cardsUnderPath(cards, entry.path).length;
        const active = entry.path === libraryState.selectedPath ? "active" : "";
        const childHtml = renderTopicTree(entry.children, cards);
        return `
        <li>
          <button class="topic-node ${active}" data-path="${escapeHtml(entry.path)}">
            <span class="topic-name">${escapeHtml(key)}</span>
            <span class="topic-count">${count}</span>
          </button>
          ${childHtml}
        </li>`;
      })
      .join("") +
    "</ul>"
  );
}

function renderLibraryArticles(cards) {
  if (cards.length === 0) {
    return `<div class="empty-state">No cards match here yet.</div>`;
  }
  return cards
    .map((c) => {
      const isCloze = c.card_type === "cloze";
      const heading = isCloze ? renderClozePreview(c.cloze_text) : c.question;
      const answerBlock = isCloze ? "" : `<div class="wiki-answer">${escapeHtml(c.answer)}</div>`;
      const images = c.media_ids.map((mid) => `<img src="${mediaUrl(mid)}" alt="" />`).join("");
      const tagChips = c.tags.map((t) => `<span class="tag-chip">${escapeHtml(t)}</span>`).join("");
      return `
      <article class="wiki-card">
        <h3 class="wiki-question">${heading}</h3>
        ${answerBlock}
        ${c.explanation ? `<div class="wiki-explanation">${c.explanation}</div>` : ""}
        ${images ? `<div class="card-images">${images}</div>` : ""}
        <div class="wiki-meta">
          <span class="card-type-pill">${isCloze ? "Cloze" : "Basic"}</span>
          ${tagChips}
          <span class="wiki-deck">Deck: ${escapeHtml(c.deck)}</span>
        </div>
      </article>`;
    })
    .join("");
}

function getVisibleLibraryCards() {
  let cards = cardsUnderPath(state.cards, libraryState.selectedPath);
  const query = libraryState.search.trim().toLowerCase();
  if (query) {
    cards = cards.filter((c) => {
      const haystack = [c.question, c.answer, c.cloze_text, c.explanation, c.tags.join(" ")]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }
  return cards;
}

function renderLibrary() {
  const tree = buildTagTree(state.cards);
  const allActive = !libraryState.selectedPath ? "active" : "";
  document.getElementById("topicTree").innerHTML =
    `<button class="topic-node topic-node-all ${allActive}" data-path="">
       <span class="topic-name">All topics</span>
       <span class="topic-count">${state.cards.length}</span>
     </button>` + renderTopicTree(tree, state.cards);

  const cards = getVisibleLibraryCards();
  document.getElementById("libraryHeading").textContent = libraryState.selectedPath || "All topics";
  document.getElementById("libraryArticles").innerHTML = renderLibraryArticles(cards);
}

// Re-roots each card's own tags under `newDeck` (using that card's current
// deck as the prefix to replace, so a batch with mixed/hand-edited decks
// still ends up consistent) and saves both fields. Shared by the Create-tab
// and Library "Change deck" actions.
async function bulkChangeDeck(cards, newDeck) {
  await Promise.all(
    cards.map((c) => {
      const oldPrefix = `${c.deck}::`;
      const newTags = c.tags.map((t) => {
        if (t === c.deck) return newDeck;
        if (t.startsWith(oldPrefix)) return `${newDeck}::${t.slice(oldPrefix.length)}`;
        return t;
      });
      return api(`/api/cards/${c.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deck: newDeck, tags: newTags }),
      }).then((updated) => {
        const idx = state.cards.findIndex((x) => x.id === c.id);
        if (idx !== -1) state.cards[idx] = updated;
      });
    })
  );
}

// ---------- Daily Notes view ----------

function relativeTime(unixSeconds) {
  const diffMs = Date.now() - unixSeconds * 1000;
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function renderDailyNotesPendingCount() {
  const textarea = document.getElementById("dailyNotesText");
  const pending = Math.max(0, textarea.value.length - state.dailyNotes.processed_length);
  document.getElementById("dailyNotesPendingCount").textContent =
    pending > 0 ? `${pending} new character${pending === 1 ? "" : "s"} since last run` : "";
}

function renderDailyNotes() {
  document.getElementById("dailyNotesTime").textContent = state.dailyNotesCardTime;

  const textarea = document.getElementById("dailyNotesText");
  if (document.activeElement !== textarea) {
    textarea.value = state.dailyNotes.text;
  }
  renderDailyNotesPendingCount();

  const runStatus = document.getElementById("dailyNotesRunStatus");
  const parts = [];
  if (state.dailyNotes.last_run_at) {
    parts.push(
      `Last run: ${relativeTime(state.dailyNotes.last_run_at)} — added ${state.dailyNotes.last_run_card_count} card${
        state.dailyNotes.last_run_card_count === 1 ? "" : "s"
      }.`
    );
  } else {
    parts.push("No runs yet.");
  }
  if (state.dailyNotes.last_run_error) {
    parts.push(`<span class="error">Last run failed: ${escapeHtml(state.dailyNotes.last_run_error)}</span>`);
  }
  if (state.dailyNotes.last_push_at) {
    if (state.dailyNotes.last_push_error) {
      parts.push(
        `<span class="error">Couldn't reach Anki ${relativeTime(state.dailyNotes.last_push_at)} ` +
          `(${escapeHtml(state.dailyNotes.last_push_error)}) — will keep retrying automatically ` +
          `while this app is running.</span>`
      );
    } else {
      parts.push(`Pushed ${state.dailyNotes.last_push_count} card${state.dailyNotes.last_push_count === 1 ? "" : "s"} to Anki ${relativeTime(state.dailyNotes.last_push_at)}.`);
    }
  }

  let questionsHtml = "";
  if (state.dailyNotes.last_run_questions.length > 0) {
    questionsHtml =
      `<ul class="daily-notes-preview">` +
      state.dailyNotes.last_run_questions.map((q) => `<li>${q}</li>`).join("") +
      `</ul>`;
  }
  runStatus.innerHTML = `<p>${parts.join(" ")}</p>${questionsHtml}`;
}

async function saveDailyNotes(text) {
  const saveState = document.getElementById("dailyNotesSaveState");
  saveState.textContent = "Saving…";
  try {
    const updated = await api("/api/daily-notes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    state.dailyNotes = updated;
    saveState.textContent = "Saved";
    renderDailyNotesPendingCount();
  } catch (err) {
    saveState.textContent = "Save failed";
    showToast(err.message, true);
  }
}

// ---------- actions ----------

async function uploadFiles(files) {
  for (const file of files) {
    try {
      const formData = new FormData();
      formData.append("file", file);
      await api("/api/sources/upload", { method: "POST", body: formData });
    } catch (err) {
      showToast(`Failed to upload ${file.name}: ${err.message}`, true);
    }
  }
  await loadProject();
}

async function processSource(id) {
  await api(`/api/sources/${id}/process`, { method: "POST" });
  await loadProject();
}

async function updateCard(id, field, value) {
  const payload = {};
  if (field === "tags") {
    payload.tags = value
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  } else if (field === "included") {
    payload.included = value;
  } else {
    payload[field] = value;
  }
  const updated = await api(`/api/cards/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const idx = state.cards.findIndex((c) => c.id === id);
  if (idx !== -1) state.cards[idx] = updated;
}

// ---------- event wiring ----------

function wireEvents() {
  document.querySelectorAll(".view-nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-nav-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      document.getElementById("createView").classList.toggle("hidden", view !== "create");
      document.getElementById("libraryView").classList.toggle("hidden", view !== "library");
      document.getElementById("dailyNotesView").classList.toggle("hidden", view !== "daily");
      if (view === "library") renderLibrary();
      if (view === "daily") renderDailyNotes();
    });
  });

  document.getElementById("topicTree").addEventListener("click", (e) => {
    const btn = e.target.closest(".topic-node");
    if (!btn) return;
    libraryState.selectedPath = btn.dataset.path || null;
    renderLibrary();
  });

  document.getElementById("librarySearch").addEventListener("input", (e) => {
    libraryState.search = e.target.value;
    renderLibrary();
  });

  document.getElementById("syncCheckBtn").addEventListener("click", async () => {
    const btn = document.getElementById("syncCheckBtn");
    btn.disabled = true;
    btn.textContent = "Checking…";
    try {
      const result = await api("/api/anki-connect/sync-check", { method: "POST" });
      await loadProject();
      const parts = [`Checked ${result.checked} pushed cards`];
      if (result.reset_card_ids.length > 0) {
        parts.push(`${result.reset_card_ids.length} were deleted in Anki and moved back to the Create tab`);
      }
      if (result.pulled_card_ids.length > 0) {
        parts.push(`${result.pulled_card_ids.length} had edits in Anki pulled back into the Library`);
      }
      if (result.reset_card_ids.length === 0 && result.pulled_card_ids.length === 0) {
        parts.push("everything matches");
      }
      showToast(parts.join(", ") + ".");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "🔄 Sync with Anki";
    }
  });

  document.getElementById("libraryChangeDeckBtn").addEventListener("click", async () => {
    const visible = getVisibleLibraryCards();
    if (visible.length === 0) return showToast("No cards to update.", true);
    const input = prompt(
      `New deck for these ${visible.length} card${visible.length === 1 ? "" : "s"}:`,
      visible[0].deck || state.deckName
    );
    if (input === null) return;
    const newDeck = input.trim();
    if (!newDeck) return showToast("Deck name can't be empty.", true);

    await bulkChangeDeck(visible, newDeck);

    // Cards already pushed to Anki (they have an anki_note_id) need the
    // move applied there too; anything not yet pushed will simply pick up
    // the new deck value the next time it's pushed from the Create tab.
    const alreadyPushedIds = visible.filter((c) => c.anki_note_id).map((c) => c.id);
    let ankiNote = "";
    if (alreadyPushedIds.length > 0) {
      try {
        const result = await api("/api/anki-connect/push", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ card_ids: alreadyPushedIds, sync_after: true }),
        });
        ankiNote = result.failed.length > 0 ? `, ${result.failed.length} failed to update in Anki` : ", moved in Anki";
      } catch (err) {
        ankiNote = " (couldn't reach Anki to move them there -- open Anki desktop and click Change deck again)";
      }
    }
    renderLibrary();
    showToast(`Moved ${visible.length} card${visible.length === 1 ? "" : "s"} to "${newDeck}"${ankiNote}.`);
  });

  document.getElementById("dailyNotesText").addEventListener("input", (e) => {
    renderDailyNotesPendingCount();
    document.getElementById("dailyNotesSaveState").textContent = "Editing…";
    clearTimeout(dailyNotesSaveTimer);
    dailyNotesSaveTimer = setTimeout(() => saveDailyNotes(e.target.value), 1200);
  });

  document.getElementById("dailyNotesRunNowBtn").addEventListener("click", async () => {
    const btn = document.getElementById("dailyNotesRunNowBtn");
    // Make sure whatever's currently typed is saved before running, rather
    // than relying on the 1.2s debounce to have already fired.
    clearTimeout(dailyNotesSaveTimer);
    const textarea = document.getElementById("dailyNotesText");
    await saveDailyNotes(textarea.value);

    btn.disabled = true;
    btn.textContent = "Running…";
    try {
      const notes = await api("/api/daily-notes/run-now", { method: "POST" });
      state.dailyNotes = notes;
      renderDailyNotes();
      showToast(
        notes.last_run_card_count > 0
          ? `Generated ${notes.last_run_card_count} card${notes.last_run_card_count === 1 ? "" : "s"}.`
          : "Ran, but there was nothing new to card."
      );
    } catch (err) {
      showToast(err.message, true);
      // The failure was likely recorded server-side (last_run_error) --
      // refresh so it shows persistently in the status line below instead
      // of only in this toast, which disappears in a few seconds.
      await loadProject();
    } finally {
      btn.disabled = false;
      btn.textContent = "▶ Run Now";
    }
  });

  document.getElementById("deckNameInput").addEventListener("change", async (e) => {
    await api("/api/project/deck-name", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: e.target.value }),
    });
  });

  document.getElementById("cardTypeToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-card-type]");
    if (!btn) return;
    state.cardType = btn.dataset.cardType;
    document
      .querySelectorAll("#cardTypeToggle button")
      .forEach((b) => b.classList.toggle("active", b === btn));
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
      btn.classList.add("active");
      document.querySelector(`.tab-panel[data-panel="${btn.dataset.tab}"]`).classList.remove("hidden");
    });
  });

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
  ["dragover", "dragenter"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    })
  );
  dropzone.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

  document.getElementById("addTextSourceBtn").addEventListener("click", async () => {
    const name = document.getElementById("textSourceName").value.trim() || "Pasted text";
    const text = document.getElementById("textSourceBody").value.trim();
    if (!text) return showToast("Enter some text first.", true);
    const formData = new FormData();
    formData.append("name", name);
    formData.append("text", text);
    await api("/api/sources/text", { method: "POST", body: formData });
    document.getElementById("textSourceName").value = "";
    document.getElementById("textSourceBody").value = "";
    showToast("Text source added and processed.");
    await loadProject();
  });

  document.getElementById("processAllBtn").addEventListener("click", async () => {
    const pending = state.sources.filter((s) => s.status === "pending" || s.status === "error");
    for (const s of pending) await processSource(s.id);
  });

  document.getElementById("sourceList").addEventListener("click", async (e) => {
    const item = e.target.closest(".source-item");
    if (!item) return;
    const id = item.dataset.id;
    if (e.target.dataset.action === "process") await processSource(id);
    if (e.target.dataset.action === "delete") {
      await api(`/api/sources/${id}`, { method: "DELETE" });
      state.selectedSourceIds.delete(id);
      await loadProject();
    }
  });

  document.getElementById("sourceCheckboxes").addEventListener("change", (e) => {
    const id = e.target.dataset.sourceId;
    if (!id) return;
    if (e.target.checked) state.selectedSourceIds.add(id);
    else state.selectedSourceIds.delete(id);
  });

  document.getElementById("generateBtn").addEventListener("click", async () => {
    const sourceIds = [...state.selectedSourceIds];
    if (sourceIds.length === 0) return showToast("Select at least one processed source.", true);
    const btn = document.getElementById("generateBtn");
    btn.disabled = true;
    btn.textContent = "Generating…";
    try {
      await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_ids: sourceIds,
          deck: document.getElementById("deckNameInput").value || "My Deck",
          card_type: state.cardType,
          subject_hint: document.getElementById("subjectHint").value || null,
          instructions: document.getElementById("instructions").value || null,
          max_cards: parseInt(document.getElementById("maxCards").value, 10) || 20,
        }),
      });
      showToast("Cards generated.");
      await loadProject();
    } catch (err) {
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ Generate Cards";
    }
  });

  document.getElementById("changeDeckBtn").addEventListener("click", async () => {
    const visible = state.cards.filter((c) => !c.archived);
    if (visible.length === 0) return;
    const input = prompt(
      `New deck for all ${visible.length} card${visible.length === 1 ? "" : "s"} in this batch:`,
      state.deckName
    );
    if (input === null) return;
    const newDeck = input.trim();
    if (!newDeck) return showToast("Deck name can't be empty.", true);

    await bulkChangeDeck(visible, newDeck);
    renderCards();
    renderTagCloud();
    showToast(`Moved ${visible.length} card${visible.length === 1 ? "" : "s"} to "${newDeck}".`);
  });

  document.getElementById("deleteAllCardsBtn").addEventListener("click", async () => {
    const visible = state.cards.filter((c) => !c.archived);
    if (visible.length === 0) return;
    if (!confirm(`Delete all ${visible.length} card${visible.length === 1 ? "" : "s"} in this batch? This can't be undone.`)) {
      return;
    }
    await Promise.all(visible.map((c) => api(`/api/cards/${c.id}`, { method: "DELETE" })));
    state.cards = state.cards.filter((c) => c.archived);
    renderCards();
    renderTagCloud();
    showToast(`Deleted ${visible.length} card${visible.length === 1 ? "" : "s"}.`);
  });

  document.getElementById("addCardBtn").addEventListener("click", async () => {
    const isCloze = state.cardType === "cloze";
    const card = await api("/api/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_type: state.cardType,
        question: isCloze ? "" : "New question",
        answer: isCloze ? "" : "New answer",
        cloze_text: isCloze ? "This is an example {{c1::cloze deletion}}." : "",
        explanation: "",
        tags: [],
        media_ids: [],
        deck: state.deckName,
        source_ids: [],
        included: true,
      }),
    });
    state.cards.push(card);
    renderCards();
    renderTagCloud();
  });

  document.getElementById("cardList").addEventListener("change", async (e) => {
    const item = e.target.closest(".card-item");
    if (!item || !e.target.dataset.field) return;
    const id = item.dataset.id;
    const field = e.target.dataset.field;
    const value = field === "included" ? e.target.checked : e.target.value;
    await updateCard(id, field, value);
    if (field === "tags") renderTagCloud();
  });

  document.getElementById("cardList").addEventListener("input", (e) => {
    const field = e.target.dataset.field;
    if (field !== "explanation" && field !== "cloze_text" && field !== "question") return;
    const item = e.target.closest(".card-item");
    const preview = item.querySelector(`[data-preview="${field}"]`);
    if (!preview) return;
    preview.innerHTML = field === "cloze_text" ? renderClozePreview(e.target.value) : e.target.value;
  });

  document.getElementById("cardList").addEventListener("click", async (e) => {
    const item = e.target.closest(".card-item");
    if (!item) return;
    if (e.target.dataset.action === "delete") {
      const id = item.dataset.id;
      await api(`/api/cards/${id}`, { method: "DELETE" });
      state.cards = state.cards.filter((c) => c.id !== id);
      renderCards();
      renderTagCloud();
    }
  });

  document.getElementById("tagCloud").addEventListener("click", async (e) => {
    const tag = e.target.dataset.tag;
    if (!tag) return;
    try {
      await navigator.clipboard.writeText(tag);
      showToast(`Copied "${tag}" — paste it into a card's Tags field.`);
    } catch (_) {}
  });

  document.getElementById("exportBtn").addEventListener("click", async () => {
    const included = state.cards.filter((c) => c.included);
    if (included.length === 0) return showToast("No cards marked for export.", true);
    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || res.statusText);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match ? match[1] : "deck.apkg";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(`Exported ${filename}`);
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("pushAnkiBtn").addEventListener("click", async () => {
    const included = state.cards.filter((c) => c.included);
    if (included.length === 0) return showToast("No cards marked for export.", true);
    const btn = document.getElementById("pushAnkiBtn");
    btn.disabled = true;
    btn.textContent = "Pushing…";
    try {
      const result = await api("/api/anki-connect/push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sync_after: true }),
      });
      const parts = [];
      if (result.added.length) parts.push(`${result.added.length} added`);
      if (result.updated.length) parts.push(`${result.updated.length} updated`);
      if (result.failed.length) parts.push(`${result.failed.length} failed`);
      const syncNote = result.synced ? ", synced to AnkiWeb" : result.sync_error ? " (sync failed)" : "";

      const pushedIds = [...result.added, ...result.updated];
      if (pushedIds.length > 0) {
        // Successfully-pushed cards are done here: archive them (hides them
        // from this Create tab, but they stay fully visible in Library) and
        // clear out the sources that fed this batch so the workspace is
        // ready for the next one. Cards that failed to push are left alone
        // so they're still there to retry.
        await Promise.all(
          pushedIds.map((id) =>
            api(`/api/cards/${id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ archived: true, included: false }),
            })
          )
        );
        await Promise.all(
          state.sources.map((s) => api(`/api/sources/${s.id}`, { method: "DELETE" }))
        );
        showToast(`Pushed to Anki: ${parts.join(", ")}${syncNote}. Workspace cleared.`, result.failed.length > 0);
        state.selectedSourceIds.clear();
        await loadProject();
      } else {
        showToast(`Push to Anki: ${parts.join(", ") || "nothing to do"}${syncNote}`, result.failed.length > 0);
      }
    } catch (err) {
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "📤 Push to Anki";
      refreshAnkiConnectStatus();
    }
  });

  setInterval(refreshAnkiConnectStatus, 15000);
}

initTheme();
wireEvents();
loadProject();
