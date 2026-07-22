const state = {
  sources: [],
  media: [],
  cards: [],
  deckName: "My Deck",
  claudeConfigured: true,
  selectedSourceIds: new Set(),
  cardType: "basic",
};

let pollHandle = null;

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
  renderAll();
  manageServerPolling();
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
  state.cards.forEach((c) => c.tags.forEach((t) => tags.add(t)));
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
  if (state.cards.length === 0) {
    list.innerHTML = `<div class="empty-state">No cards yet. Generate from your sources, or add one manually.</div>`;
    return;
  }
  list.innerHTML = state.cards
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
            <div class="card-field-label">Question</div>
            <textarea data-field="question">${escapeHtml(c.question)}</textarea>
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
    if (field !== "explanation" && field !== "cloze_text") return;
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
}

wireEvents();
loadProject();
