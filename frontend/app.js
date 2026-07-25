const state = {
  sources: [],
  media: [],
  cards: [],
  deckName: "My Deck",
  claudeConfigured: true,
  selectedSourceIds: new Set(),
  cardType: "basic",
  outputMode: "cards",
  referenceNotes: [],
  ankiConnectAvailable: false,
  ankiDecks: [],
  dailyNotes: {
    text: "", processed_length: 0, last_run_at: null, last_run_card_count: 0, last_run_error: null,
    last_run_questions: [], last_push_at: null, last_push_count: 0, last_push_error: null,
  },
  dailyNotesCardTime: "23:59",
};

const libraryState = {
  selectedPath: null, // null = "All topics"
  search: "",
  kind: "all", // all | reference | cards
  focusSection: null, // section title to auto-open/scroll to after navigating
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
  state.referenceNotes = data.reference_notes || [];
  state.deckName = data.deck_name;
  state.claudeConfigured = data.claude_configured;
  state.dailyNotes = data.daily_notes;
  state.dailyNotesCardTime = data.daily_notes_card_time;
  renderAll();
  manageServerPolling();
  refreshAnkiConnectStatus();
}

async function refreshAnkiConnectStatus() {
  const wasAvailable = state.ankiConnectAvailable;
  try {
    const data = await api("/api/anki-connect/status");
    state.ankiConnectAvailable = data.available;
  } catch (_) {
    state.ankiConnectAvailable = false;
  }
  renderAnkiConnectStatus();
  // Only worth re-fetching when Anki just became reachable -- avoids a
  // pointless request every 15s poll while it's known to be unavailable.
  if (state.ankiConnectAvailable && !wasAvailable) {
    refreshDeckSuggestions();
  }
}

async function refreshDeckSuggestions() {
  try {
    const data = await api("/api/anki-connect/decks");
    state.ankiDecks = data.decks;
  } catch (_) {
    // Autocomplete is a bonus, not worth surfacing an error over.
  }
}

// Custom-styled combobox: a plain text input (still free-typeable, so a
// brand-new deck name works fine) paired with a dropdown of matching real
// Anki decks, since the native <datalist> UI can't be restyled to match
// the rest of the app.
function attachDeckAutocomplete(input) {
  const list = input.parentElement.querySelector(".deck-suggest-list");
  if (!list || input.dataset.autocompleteAttached) return;
  input.dataset.autocompleteAttached = "1";

  function show() {
    const query = input.value.trim().toLowerCase();
    const matches = state.ankiDecks.filter((d) => d.toLowerCase().includes(query));
    if (matches.length === 0 || (matches.length === 1 && matches[0].toLowerCase() === query)) {
      list.classList.add("hidden");
      list.innerHTML = "";
      return;
    }
    list.innerHTML = matches
      .slice(0, 20)
      .map((d) => `<div class="deck-suggest-item" data-value="${escapeHtml(d)}">${escapeHtml(d)}</div>`)
      .join("");
    list.classList.remove("hidden");
  }

  input.addEventListener("focus", show);
  input.addEventListener("input", show);
  input.addEventListener("blur", () => {
    // Delay so a click on a suggestion (see mousedown below) registers
    // before the list disappears.
    setTimeout(() => list.classList.add("hidden"), 150);
  });
  list.addEventListener("mousedown", (e) => {
    const item = e.target.closest(".deck-suggest-item");
    if (!item) return;
    e.preventDefault(); // keep focus on the input instead of blurring first
    input.value = item.dataset.value;
    list.classList.add("hidden");
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function attachAllDeckAutocompletes(root = document) {
  root.querySelectorAll(".deck-autocomplete input").forEach(attachDeckAutocomplete);
}

const CARD_TYPE_HINTS = {
  basic: "One question, one answer.",
  cloze: "A sentence with a word or two blanked out.",
  sequence:
    "A whole list on ONE card — everything hidden, revealed one item at a time. For mnemonics, scored criteria, and protocol steps.",
};

/** Shows the tail of a deck path -- the part that identifies it -- with the
 *  parent levels dimmed, rather than clipping the middle of a long path. */
function renderDeckDisplay() {
  const el = document.getElementById("deckDisplay");
  const full = state.deckName || "";
  if (!full) {
    el.innerHTML = `<span class="deck-display-dim">Choose a deck…</span>`;
    el.title = "Click to change deck";
    return;
  }
  const parts = full.split("::");
  const leaf = parts[parts.length - 1];
  const hasParents = parts.length > 1;
  el.innerHTML = hasParents
    ? `<span class="deck-display-dim">…::</span>${escapeHtml(leaf)}`
    : escapeHtml(leaf);
  el.title = full;
}

function startEditingDeck() {
  const field = document.getElementById("deckNameField");
  field.classList.add("editing");
  const input = document.getElementById("deckNameInput");
  input.focus();
  input.select();
}

function stopEditingDeck() {
  document.getElementById("deckNameField").classList.remove("editing");
  renderDeckDisplay();
}

function renderCardTypeHint() {
  document.getElementById("cardTypeHint").textContent = CARD_TYPE_HINTS[state.cardType] || "";
}

function renderOutputMode() {
  const isReference = state.outputMode === "reference";
  document.getElementById("cardOnlyOptions").classList.toggle("hidden", isReference);
  document.getElementById("maxCardsRow").classList.toggle("hidden", isReference);
  document.getElementById("outputModeHint").textContent = isReference
    ? "A wiki page kept in the Library for looking up later — no flashcards, nothing pushed to Anki."
    : "Quizzable cards pushed to Anki.";
  document.getElementById("generateBtn").textContent = isReference
    ? "📖 Generate Reference Page"
    : "✨ Generate Cards";
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
  renderDeckDisplay();
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

function renderSequencePreview(items) {
  const list = (items || []).filter((i) => i && i.trim());
  if (list.length === 0) return `<em>(no items yet)</em>`;
  return (
    `<ol class="seq-preview">` +
    list.map((i) => `<li>${escapeHtml(i.trim())}</li>`).join("") +
    `</ol>`
  );
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
      const isSequence = c.card_type === "sequence";
      const frontFields = isSequence
        ? `
            <div class="card-field-label">Prompt (names the list)</div>
            <textarea data-field="sequence_prompt">${escapeHtml(c.sequence_prompt || "")}</textarea>
            <div class="card-field-label">List items — one per line, in order</div>
            <p class="field-hint" style="margin: -4px 0 2px 0;">All hidden on the front; revealed one at a time.</p>
            <textarea class="explanation" data-field="sequence_items">${escapeHtml((c.sequence_items || []).join("\n"))}</textarea>
            <div class="card-field-label">Preview</div>
            <div class="explanation-preview" data-preview="sequence_items">${renderSequencePreview(c.sequence_items)}</div>`
        : isCloze
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
            <span class="card-type-pill">${isSequence ? "List" : isCloze ? "Cloze" : "Basic"}</span>
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
              Deck:
              <div class="deck-autocomplete">
                <input type="text" data-field="deck" value="${escapeHtml(c.deck)}" autocomplete="off" />
                <div class="deck-suggest-list hidden"></div>
              </div>
              <button class="icon-btn" data-action="delete">Delete card</button>
            </div>
          </div>
        </div>
      </div>`;
    })
    .join("");
  attachAllDeckAutocompletes(list);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------- Library view ----------

function cardsUnderPath(cards, path) {
  if (!path) return cards;
  return cards.filter((c) => c.tags.some((t) => t === path || t.startsWith(path + "::")));
}

function matchesLibraryQuery(item, query) {
  const haystack = [
    item.question, item.answer, item.cloze_text, item.explanation,
    item.title, item.summary, item.body,
    (item.sequence_items || []).join(" "), item.sequence_prompt,
    (item.tags || []).join(" "),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

// ---------- topic pages ----------
//
// The Library is a wiki, not a card list: a topic is a *page*, and every
// card or reference note tagged under it is content on that page. Deeper
// topics become links out to their own pages rather than being flattened
// into this one.

function allLibraryItems() {
  return [...state.referenceNotes, ...state.cards];
}

/** Items whose tag sits exactly at `path` -- this page's own content,
 *  excluding anything belonging to a deeper subtopic page. */
function itemsExactlyAt(items, path) {
  if (!path) return items.filter((i) => (i.tags || []).length === 0);
  return items.filter((i) => (i.tags || []).some((t) => t === path));
}

/** Direct child topic names under `path`, with a recursive item count. */
function childTopics(items, path) {
  const prefix = path ? path + "::" : "";
  const names = new Set();
  for (const item of items) {
    for (const tag of item.tags || []) {
      if (path && !tag.startsWith(prefix)) continue;
      const rest = path ? tag.slice(prefix.length) : tag;
      const head = rest.split("::")[0].trim();
      if (head) names.add(head);
    }
  }
  return [...names].sort((a, b) => a.localeCompare(b)).map((name) => {
    const childPath = prefix + name;
    const all = cardsUnderPath(items, childPath);
    return {
      name,
      path: childPath,
      total: all.length,
      notes: all.filter((i) => i.body !== undefined).length,
      cards: all.filter((i) => i.body === undefined).length,
      subtopics: childTopicNames(items, childPath).length,
    };
  });
}

function childTopicNames(items, path) {
  const prefix = path + "::";
  const names = new Set();
  for (const item of items) {
    for (const tag of item.tags || []) {
      if (!tag.startsWith(prefix)) continue;
      const head = tag.slice(prefix.length).split("::")[0].trim();
      if (head) names.add(head);
    }
  }
  return [...names];
}

function renderBreadcrumb(path) {
  const crumbs = [`<button class="crumb" data-path="">Library</button>`];
  if (path) {
    const parts = path.split("::");
    parts.forEach((part, i) => {
      const sub = parts.slice(0, i + 1).join("::");
      const isLast = i === parts.length - 1;
      crumbs.push(
        isLast
          ? `<span class="crumb current">${escapeHtml(part)}</span>`
          : `<button class="crumb" data-path="${escapeHtml(sub)}">${escapeHtml(part)}</button>`
      );
    });
  }
  return `<nav class="wiki-breadcrumb">${crumbs.join('<span class="crumb-sep">›</span>')}</nav>`;
}

/** AMBOSS-style drill-down: one column per level of the path you've walked,
 *  each a plain list of child topics, so you can see where you are and step
 *  back sideways without losing context. */
function renderColumnBrowser(path) {
  const items = allLibraryItems();
  const levels = [];
  levels.push({ title: "Library", parent: null, children: childTopics(items, null) });
  if (path) {
    const parts = path.split("::");
    for (let i = 0; i < parts.length; i++) {
      const sub = parts.slice(0, i + 1).join("::");
      const kids = childTopics(items, sub);
      if (kids.length === 0) break;
      levels.push({ title: parts[i], parent: sub, children: kids });
    }
  }

  const selectedAtLevel = (level) => {
    if (!path) return null;
    const parts = path.split("::");
    const depth = level.parent ? level.parent.split("::").length : 0;
    return parts.length > depth ? parts.slice(0, depth + 1).join("::") : null;
  };

  return `
    <div class="col-browser">
      ${levels
        .map((level) => {
          const sel = selectedAtLevel(level);
          return `
        <div class="col-browser-col">
          <h3 class="col-browser-title">${escapeHtml(level.title)}</h3>
          <div class="col-browser-list">
            ${level.children
              .map((c) => {
                const active = c.path === sel ? "active" : "";
                const hasKids = c.subtopics > 0;
                return `
              <button class="col-row ${active}" data-path="${escapeHtml(c.path)}">
                <span class="col-row-icon">${hasKids ? "🗂️" : "📄"}</span>
                <span class="col-row-name">${escapeHtml(c.name)}</span>
                <span class="col-row-count">${c.total}</span>
                ${hasKids ? `<span class="col-row-chevron">›</span>` : ""}
              </button>`;
              })
              .join("")}
          </div>
        </div>`;
        })
        .join("")}
    </div>`;
}

/** Splits reference-note body HTML on its <h4> headings so each becomes its
 *  own collapsible section, matching how a wiki article reads. */
function splitBodyIntoSections(bodyHtml) {
  const holder = document.createElement("div");
  holder.innerHTML = bodyHtml || "";
  const sections = [];
  let current = null;
  for (const node of Array.from(holder.childNodes)) {
    if (node.nodeName === "H4") {
      if (current) sections.push(current);
      current = { title: node.textContent, html: "" };
    } else {
      if (!current) current = { title: "Overview", html: "" };
      current.html += node.outerHTML || node.textContent || "";
    }
  }
  if (current) sections.push(current);
  return sections;
}

function renderAccordion(sections) {
  return sections
    .map((s) => {
      const focused = libraryState.focusSection && s.title === libraryState.focusSection;
      return `
    <section class="acc ${s.open === false && !focused ? "" : "open"} ${focused ? "focused" : ""}"
             ${s.sectionPath ? `data-section-path="${escapeHtml(s.sectionPath)}"` : ""}>
      <button class="acc-head" type="button">
        <span class="acc-title">${escapeHtml(s.title)}</span>
        <span class="acc-chevron">⌄</span>
      </button>
      <div class="acc-body">${s.html}</div>
    </section>`;
    })
    .join("");
}

/** Every topic's leaf name -> its full path, longest name first so
 *  "Cyanide Poisoning" wins over a hypothetical "Cyanide". */
function topicLinkIndex() {
  const index = [];
  const seen = new Set();
  for (const item of allLibraryItems()) {
    for (const tag of item.tags || []) {
      const parts = tag.split("::");
      // Skip level 0 (the deck root) -- linking every mention of the deck
      // name to the library root is noise.
      for (let i = 1; i < parts.length; i++) {
        const leaf = parts[i].trim();
        const path = parts.slice(0, i + 1).join("::");
        const key = leaf.toLowerCase();
        if (leaf.length < 4 || seen.has(key)) continue;
        seen.add(key);
        index.push({ leaf, path });
      }
    }
  }
  return index.sort((a, b) => b.leaf.length - a.leaf.length);
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Turns mentions of other topics into links to their pages -- the wiki
 *  cross-reference behaviour. Walks text nodes only, so it can never break
 *  existing markup or double-link inside an anchor we just made. */
function linkifyTopics(html, currentPath) {
  const index = topicLinkIndex().filter((e) => e.path !== currentPath);
  if (index.length === 0) return html;

  const holder = document.createElement("div");
  holder.innerHTML = html;

  const walker = document.createTreeWalker(holder, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      // Don't touch text already inside a link or a heading.
      if (node.parentElement.closest("a, .topic-link, h1, h2, h3, h4")) {
        return NodeFilter.FILTER_REJECT;
      }
      return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  // ONE combined pass per text node. Replacing leaf-by-leaf would re-scan the
  // markup inserted by earlier leaves and match inside its attributes,
  // corrupting the link (and it did -- a data-path came out containing HTML).
  const byLeaf = new Map(index.map((e) => [e.leaf.toLowerCase(), e.path]));
  const combined = new RegExp(
    `\\b(${index.map((e) => escapeRegExp(e.leaf)).join("|")})\\b`,
    "gi"
  );

  for (const node of textNodes) {
    const source = node.nodeValue;
    combined.lastIndex = 0;
    if (!combined.test(source)) continue;
    combined.lastIndex = 0;

    const linkedOnce = new Set();
    const html = escapeHtml(source).replace(combined, (match) => {
      const key = match.toLowerCase();
      const path = byLeaf.get(key);
      // Link only the first mention of a given topic per text node, the way
      // a wiki links a term once rather than on every occurrence.
      if (!path || linkedOnce.has(key)) return match;
      linkedOnce.add(key);
      return `<button class="topic-link" data-path="${escapeHtml(path)}">${match}</button>`;
    });

    const frag = document.createElement("span");
    frag.innerHTML = html;
    node.parentNode.replaceChild(frag, node);
  }
  return holder.innerHTML;
}

/** A cloze sentence read as prose: blanks filled in and emphasized, so the
 *  page reads like an article instead of a fill-in-the-blank exercise. */
function clozeAsProse(text) {
  const escaped = escapeHtml(text || "");
  return escaped.replace(/\{\{c\d+::(.*?)(?:::.*?)?\}\}/g, (_m, inner) => `<strong>${inner}</strong>`);
}

function renderFact(item) {
  if (item.card_type === "sequence") {
    return `
      <div class="wiki-fact">
        <div class="wiki-fact-lead">${escapeHtml(item.sequence_prompt || "")}</div>
        ${renderSequencePreview(item.sequence_items)}
        ${item.explanation ? `<div class="wiki-fact-detail">${item.explanation}</div>` : ""}
      </div>`;
  }
  if (item.card_type === "cloze") {
    return `
      <div class="wiki-fact">
        <div class="wiki-fact-lead">${clozeAsProse(item.cloze_text)}</div>
        ${item.explanation ? `<div class="wiki-fact-detail">${item.explanation}</div>` : ""}
      </div>`;
  }
  // The question is the point of the fact, so it leads; the answer follows
  // as its emphasized resolution. (Leading with the bare answer and burying
  // the question underneath read backwards -- you couldn't tell what was
  // being claimed.)
  return `
    <div class="wiki-fact">
      <div class="wiki-fact-lead">${item.question}</div>
      <div class="wiki-fact-answer">${escapeHtml(item.answer)}</div>
      ${item.explanation ? `<div class="wiki-fact-detail">${item.explanation}</div>` : ""}
    </div>`;
}

function renderTopicPage(path) {
  const items = allLibraryItems();
  const children = childTopics(items, path);
  const own = itemsExactlyAt(items, path);
  const ownNotes = own.filter((i) => i.body !== undefined);
  const ownCards = own.filter((i) => i.body === undefined);

  // Leaf children roll UP into this page as sections rather than becoming
  // their own thin pages -- "Airway" is the article, "LMA" is a heading in
  // it, the way a wiki article has sections. A child that has children of
  // its own still gets a page and stays a link.
  const leafChildren = children.filter((c) => c.subtopics === 0);
  const branchChildren = children.filter((c) => c.subtopics > 0);

  // Nothing here and nothing rollable: pure index, browse it as columns.
  if (branchChildren.length > 0 && own.length === 0 && leafChildren.length === 0) {
    return renderBreadcrumb(path) + renderColumnBrowser(path);
  }

  const title = path ? path.split("::").pop() : "Library";
  const totalUnder = path ? cardsUnderPath(items, path).length : items.length;

  const parts = [renderBreadcrumb(path)];
  parts.push(`<h1 class="wiki-page-title">${escapeHtml(title)}</h1>`);
  parts.push(
    `<p class="wiki-page-meta">${totalUnder} item${totalUnder === 1 ? "" : "s"}${
      branchChildren.length ? ` · ${branchChildren.length} subtopic${branchChildren.length === 1 ? "" : "s"}` : ""
    }</p>`
  );

  const sections = [];

  for (const n of ownNotes) {
    if (n.summary) {
      sections.push({
        title: "Summary",
        html: `<div class="wiki-summary-body" data-ref-id="${escapeHtml(n.id)}">
                 <p>${escapeHtml(n.summary)}</p>
                 <button class="icon-btn" data-action="delete-reference">Delete this note</button>
               </div>`,
      });
    }
    for (const s of splitBodyIntoSections(n.body)) {
      sections.push({ title: s.title, html: `<div class="wiki-body">${s.html}</div>` });
    }
    if (n.media_ids.length) {
      sections.push({
        title: "Images",
        html: `<div class="card-images">${n.media_ids
          .map((mid) => `<img src="${mediaUrl(mid)}" alt="" />`)
          .join("")}</div>`,
      });
    }
  }

  // Content filed directly at this topic, with no subtopic name to head it.
  if (ownCards.length > 0) {
    sections.push({
      title: path ? "General" : "Uncategorized",
      html: `<div class="wiki-facts">${ownCards.map(renderFact).join("")}</div>`,
    });
  }

  // Each leaf subtopic becomes a named section here rather than its own page.
  for (const child of leafChildren) {
    const childItems = cardsUnderPath(items, child.path);
    const childNotes = childItems.filter((i) => i.body !== undefined);
    const childCards = childItems.filter((i) => i.body === undefined);
    let html = "";
    for (const n of childNotes) {
      if (n.summary) html += `<p class="wiki-summary">${escapeHtml(n.summary)}</p>`;
      if (n.body) html += `<div class="wiki-body">${n.body}</div>`;
    }
    if (childCards.length) {
      html += `<div class="wiki-facts">${childCards.map(renderFact).join("")}</div>`;
    }
    sections.push({ title: child.name, html, sectionPath: child.path });
  }

  if (branchChildren.length > 0) {
    sections.push({
      title: `Subtopics (${branchChildren.length})`,
      isNav: true,
      html: `<div class="col-browser-list inline">${branchChildren
        .map(
          (c) => `
          <button class="col-row" data-path="${escapeHtml(c.path)}">
            <span class="col-row-icon">🗂️</span>
            <span class="col-row-name">${escapeHtml(c.name)}</span>
            <span class="col-row-count">${c.total}</span>
            <span class="col-row-chevron">›</span>
          </button>`
        )
        .join("")}</div>`,
    });
  }

  if (sections.length === 0) {
    parts.push(`<div class="empty-state">Nothing filed under this topic yet.</div>`);
  } else {
    // Cross-link mentions of other topics, but only in the prose sections --
    // the nav list is already links, and re-linking it would nest buttons.
    const linked = sections.map((s) =>
      s.isNav ? s : { ...s, html: linkifyTopics(s.html, path) }
    );
    parts.push(renderAccordion(linked));
  }
  return parts.join("");
}

function renderSearchResults(query) {
  const items = allLibraryItems().filter((i) => matchesLibraryQuery(i, query));
  const parts = [
    renderBreadcrumb(null),
    `<h1 class="wiki-page-title">Search</h1>`,
    `<p class="wiki-page-meta">${items.length} result${items.length === 1 ? "" : "s"} for “${escapeHtml(query)}”</p>`,
  ];
  if (items.length === 0) {
    parts.push(`<div class="empty-state">No matches.</div>`);
    return parts.join("");
  }
  parts.push(
    `<div class="wiki-facts">` +
      items
        .map((i) => {
          const topic = (i.tags || [])[0] || "";
          const lead = i.body !== undefined ? escapeHtml(i.title) : null;
          return `
        <div class="wiki-fact search-hit">
          ${topic ? `<button class="search-hit-topic" data-path="${escapeHtml(topic)}">${escapeHtml(topic)}</button>` : ""}
          ${lead !== null ? `<div class="wiki-fact-lead">📖 ${lead}</div>` : renderFact(i)}
        </div>`;
        })
        .join("") +
      `</div>`
  );
  return parts.join("");
}

/** A leaf topic has no page of its own -- it lives as a section on its
 *  parent's page -- so navigating to one opens the parent and focuses that
 *  section instead of rendering a near-empty page for it. */
function navigateToTopic(path) {
  libraryState.focusSection = null;
  if (path) {
    const items = allLibraryItems();
    const isLeaf = childTopicNames(items, path).length === 0;
    const parts = path.split("::");
    if (isLeaf && parts.length > 1) {
      libraryState.selectedPath = parts.slice(0, -1).join("::");
      libraryState.focusSection = parts[parts.length - 1];
    } else {
      libraryState.selectedPath = path;
    }
  } else {
    libraryState.selectedPath = null;
  }
  libraryState.search = "";
  document.getElementById("librarySearch").value = "";
  renderLibrary();

  const focused = document.querySelector(".acc.focused");
  (focused || document.getElementById("libraryArticles")).scrollIntoView({
    block: focused ? "center" : "start",
    behavior: "smooth",
  });
}

function renderLibrary() {
  const query = libraryState.search.trim().toLowerCase();
  document.getElementById("libraryArticles").innerHTML = query
    ? renderSearchResults(query)
    : renderTopicPage(libraryState.selectedPath);
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
  } else if (field === "sequence_items") {
    payload.sequence_items = value
      .split("\n")
      .map((i) => i.trim())
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

  document.getElementById("reorganizeTopicsBtn").addEventListener("click", async () => {
    const btn = document.getElementById("reorganizeTopicsBtn");
    if (!confirm("Re-file stray topics under broader disciplines? This changes tags on your cards (and in Anki next time you push).")) return;
    btn.disabled = true;
    btn.textContent = "Tidying…";
    try {
      const result = await api("/api/cards/reorganize-topics", { method: "POST" });
      await loadProject();
      libraryState.selectedPath = null;
      renderLibrary();
      if (result.mapping.length === 0) {
        showToast("Topics already look well organized — nothing moved.");
      } else {
        showToast(
          `Re-filed ${result.mapping.length} topic${result.mapping.length === 1 ? "" : "s"} ` +
            `across ${result.moved} item${result.moved === 1 ? "" : "s"}.`
        );
      }
    } catch (err) {
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "🗂️ Tidy up topics";
    }
  });

  document.getElementById("libraryChangeDeckBtn").addEventListener("click", async () => {
    // Every card under the topic currently being viewed, subtopics included.
    const visible = cardsUnderPath(state.cards, libraryState.selectedPath);
    if (visible.length === 0) return showToast("No cards under this topic.", true);
    const where = libraryState.selectedPath || "the whole library";
    const input = prompt(
      `New deck for the ${visible.length} card${visible.length === 1 ? "" : "s"} under ${where}:`,
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
    state.deckName = e.target.value;
    await api("/api/project/deck-name", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: e.target.value }),
    });
    renderDeckDisplay();
  });

  const deckDisplay = document.getElementById("deckDisplay");
  deckDisplay.addEventListener("click", startEditingDeck);
  deckDisplay.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      startEditingDeck();
    }
  });
  document.getElementById("deckNameInput").addEventListener("blur", () => {
    // Let a click on an autocomplete suggestion land before collapsing.
    setTimeout(stopEditingDeck, 180);
  });
  document.getElementById("deckNameInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "Escape") e.target.blur();
  });

  document.getElementById("cardTypeToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-card-type]");
    if (!btn) return;
    state.cardType = btn.dataset.cardType;
    document
      .querySelectorAll("#cardTypeToggle button")
      .forEach((b) => b.classList.toggle("active", b === btn));
    renderCardTypeHint();
  });

  document.getElementById("outputModeToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-output-mode]");
    if (!btn) return;
    state.outputMode = btn.dataset.outputMode;
    document
      .querySelectorAll("#outputModeToggle button")
      .forEach((b) => b.classList.toggle("active", b === btn));
    renderOutputMode();
  });

  document.getElementById("libraryArticles").addEventListener("click", async (e) => {
    const accHead = e.target.closest(".acc-head");
    if (accHead) {
      accHead.parentElement.classList.toggle("open");
      return;
    }

    // In-page wiki navigation: breadcrumbs, subtopic links, search hits.
    const nav = e.target.closest("[data-path]");
    if (nav) {
      navigateToTopic(nav.dataset.path || null);
      return;
    }

    if (e.target.dataset.action !== "delete-reference") return;
    const article = e.target.closest("[data-ref-id]");
    if (!article) return;
    const id = article.dataset.refId;
    if (!confirm("Delete this reference page? This can't be undone.")) return;
    await api(`/api/reference/${id}`, { method: "DELETE" });
    state.referenceNotes = state.referenceNotes.filter((n) => n.id !== id);
    renderLibrary();
    showToast("Reference page deleted.");
  });

  document.querySelector(".notes-toolbar").addEventListener("click", (e) => {
    const btn = e.target.closest(".notes-tool-btn");
    if (!btn) return;
    const textarea = document.getElementById("dailyNotesText");
    const prefix = { bullet: "• ", number: "1. ", indent: "    " }[btn.dataset.insert] || "";
    const pos = textarea.selectionStart;
    const before = textarea.value.slice(0, pos);
    const after = textarea.value.slice(pos);
    // Start a fresh line unless the cursor is already at the start of one.
    const lead = before === "" || before.endsWith("\n") ? "" : "\n";
    textarea.value = `${before}${lead}${prefix}${after}`;
    const newPos = pos + lead.length + prefix.length;
    textarea.setSelectionRange(newPos, newPos);
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
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
      const result = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_ids: sourceIds,
          deck: document.getElementById("deckNameInput").value || "My Deck",
          card_type: state.cardType,
          output_mode: state.outputMode,
          subject_hint: document.getElementById("subjectHint").value || null,
          instructions: document.getElementById("instructions").value || null,
          max_cards: parseInt(document.getElementById("maxCards").value, 10) || 20,
        }),
      });
      await loadProject();
      if (result.output_mode === "reference") {
        showToast(`Reference page "${result.reference_note.title}" saved to your Library.`);
      } else {
        showToast(`Generated ${result.cards.length} card${result.cards.length === 1 ? "" : "s"}.`);
      }
    } catch (err) {
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      renderOutputMode();
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
    const isSequence = state.cardType === "sequence";
    const isBasic = !isCloze && !isSequence;
    const card = await api("/api/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_type: state.cardType,
        question: isBasic ? "New question" : "",
        answer: isBasic ? "New answer" : "",
        cloze_text: isCloze ? "This is an example {{c1::cloze deletion}}." : "",
        sequence_prompt: isSequence ? "Name the items in this list" : "",
        sequence_items: isSequence ? ["First item", "Second item", "Third item"] : [],
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
    if (!["explanation", "cloze_text", "question", "sequence_items"].includes(field)) return;
    const item = e.target.closest(".card-item");
    const preview = item.querySelector(`[data-preview="${field}"]`);
    if (!preview) return;
    if (field === "cloze_text") {
      preview.innerHTML = renderClozePreview(e.target.value);
    } else if (field === "sequence_items") {
      preview.innerHTML = renderSequencePreview(e.target.value.split("\n"));
    } else {
      preview.innerHTML = e.target.value;
    }
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
attachAllDeckAutocompletes();
renderOutputMode();
loadProject();
