const view = document.querySelector("#view");
const navButtons = document.querySelectorAll(".nav-btn");

const state = {
  page: "home",
  cardId: null,
  jobTimer: null,
  driveTimer: null,
  drivePopup: null,
  drive: null,
  audio: null,
  cards: [],
  query: "",
  author: "",
  category: "",
};

navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.cardId = null;
    show(button.dataset.view);
  });
});

function show(page) {
  stopPlayback();
  stopJobPoll();
  stopDrivePoll();
  state.page = page;
  state.cardId = page === "library" ? state.cardId : null;
  navButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === page);
  });
  if (page === "home") loadHome();
  if (page === "library") loadLibrary();
  if (page === "add") loadAdd();
  if (page === "cloud") loadCloud();
  if (page === "settings") loadSettings();
}

function loadHome() {
  const mark = (path) => `<span class="step-mark" aria-hidden="true"><svg viewBox="0 0 24 24">${path}</svg></span>`;
  view.innerHTML = `
    <section class="home">
      <header class="home-intro">
        <h2>YotoLib is a tool that lets you back up your Yoto cards</h2>
        <p class="lede">Paste a card’s link and it saves the cover, the audio, and the card details on this computer. It also keeps a second copy you can store somewhere else. Only back up cards you legally own.</p>
      </header>
      <ol class="steps">
        <li>
          ${mark('<path d="M10.2 13.2a4.2 4.2 0 0 0 6 .1l1.7-1.7a4.2 4.2 0 0 0-6-6L10.6 6.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M13.8 10.8a4.2 4.2 0 0 0-6-.1l-1.7 1.7a4.2 4.2 0 0 0 6 6l1.3-1.3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>')}
          <div class="step-copy">
            <strong>Get the card’s link.</strong>
            <p>Hold the card to your phone with an NFC app such as NXP TagInfo, then copy the link it shows.</p>
          </div>
        </li>
        <li>
          ${mark('<path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>')}
          <div class="step-copy">
            <strong>Add your cards.</strong>
            <p>Paste one or more links. YotoLib saves each card in your library, with its cover, tracks, and <code>card.json</code>.</p>
          </div>
        </li>
        <li>
          ${mark('<rect x="8" y="8" width="11" height="11" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M6 15V5.5A1.5 1.5 0 0 1 7.5 4H16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>')}
          <div class="step-copy">
            <strong>Keep a spare copy.</strong>
            <p>A zip of that card goes in your backup folder, separate from the library files. From Cloud backup you can also copy the library to a Google Drive folder.</p>
          </div>
        </li>
        <li>
          ${mark('<path d="M8 7h9M8 12h9M8 17h6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M4.5 7h.01M4.5 12h.01M4.5 17h.01" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>')}
          <div class="step-copy">
            <strong>Keep a recovery list.</strong>
            <p><code>recovery.json</code> in the backup folder remembers each card’s id, title, and link, so you can download them again if the library files are lost.</p>
          </div>
        </li>
      </ol>
      <div class="home-actions">
        <button type="button" class="primary" id="go-add">Add cards</button>
        <button type="button" class="ghost" id="go-library">Open library</button>
      </div>
    </section>`;
  document.querySelector("#go-library").addEventListener("click", () => show("library"));
  document.querySelector("#go-add").addEventListener("click", () => show("add"));
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed.");
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function termsMarkup() {
  return `
    <section class="terms" aria-labelledby="terms-heading">
      <h3 id="terms-heading">Terms of use</h3>
      <p>YotoLib saves a copy of your cards on this computer. Use it only for cards you legally own, or cards you already have permission to keep a copy of.</p>
      <p>Before a download starts, you confirm that:</p>
      <ul>
        <li>You legally own every card you are downloading, or the owner has allowed you to keep a personal copy.</li>
        <li>You will not use YotoLib to copy a card you do not have a right to store.</li>
        <li>You will keep the saved audio, covers, and other files for yourself. You will not share, sell, or publish them unless you already have permission.</li>
        <li>The audio, covers, artwork, and other card content belong to their owners. YotoLib does not give you any rights in that content.</li>
        <li>Owning the physical card does not, by itself, mean a digital copy is allowed. You are responsible for making sure your copy is allowed.</li>
        <li>YotoLib is not made by Yoto, and it is not affiliated with Yoto.</li>
      </ul>
      <p>The app is provided as is, with no warranty. The people who made it are not responsible for how you use it, for the card content, or for lost files.</p>
    </section>`;
}

function coverMarkup(card, className) {
  const letter = escapeHtml((card.title || "?").slice(0, 1));
  if (!card.cover) {
    return `<div class="${className} cover-fallback" aria-hidden="true">${letter}</div>`;
  }
  const src = `/api/cards/${encodeURIComponent(card.cardId)}/files/${encodeURIComponent(card.cover)}`;
  return `<img class="${className}" alt="" src="${src}" onerror="this.outerHTML='<div class=&quot;${className} cover-fallback&quot; aria-hidden=&quot;true&quot;>${letter}</div>'">`;
}

const ACCENTS = ["blue", "green", "purple", "coral", "yellow", "peach"];

const ICON_AUDIO = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V6l10-2v12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="7" cy="18" r="2.2" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="17" cy="16" r="2.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`;
const ICON_CHECK = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 9.2 17 19 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_ALERT = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.5 3.5 19.5h17L12 4.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 10v4.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="16.8" r="0.8" fill="currentColor"/></svg>`;
const ICON_SEARCH = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M16 16.5 20 20.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
const ICON_PLAY = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6.2v11.6L18 12z" fill="currentColor"/></svg>`;
const ICON_PAUSE = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 5.5h3v13h-3zM13.5 5.5h3v13h-3z" fill="currentColor"/></svg>`;
const ICON_PREV = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 6v12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M17.5 6.8 9 12l8.5 5.2z" fill="currentColor"/></svg>`;
const ICON_NEXT = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 6v12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M6.5 6.8 15 12 6.5 17.2z" fill="currentColor"/></svg>`;

function stopPlayback() {
  const audio = state.audio;
  state.audio = null;
  if (!audio) return;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

function cardFileUrl(cardId, relative) {
  const path = String(relative)
    .replaceAll("\\", "/")
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/api/cards/${encodeURIComponent(cardId)}/files/${path}`;
}

function formatClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const secs = total % 60;
  const mins = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  if (hours) return `${hours}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function accentFor(category) {
  let total = 0;
  for (const char of category) total += char.charCodeAt(0);
  return ACCENTS[total % ACCENTS.length];
}

function backupMarkup(card) {
  if (card.backedUp) {
    return `<span class="status status-ok">${ICON_CHECK}Backed up</span>`;
  }
  return `<span class="status status-warn">${ICON_ALERT}Needs a backup</span>`;
}

function backupSummary(list) {
  const backed = list.filter((card) => card.backedUp).length;
  const needs = list.length - backed;
  const parts = [`${backed} backed up`];
  if (needs) parts.push(`${needs} ${needs === 1 ? "needs" : "need"} a backup`);
  return parts.join(" · ");
}

function uniqueValues(cards, field) {
  const values = new Set();
  cards.forEach((card) => {
    const value = (card[field] || "").trim();
    if (value) values.add(value);
  });
  return [...values].sort((a, b) => a.localeCompare(b));
}

function cardMatches(card, query, author, category) {
  if (author && (card.author || "") !== author) return false;
  if (category && (card.category || "") !== category) return false;
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = [
    card.title,
    card.author,
    card.category,
    ...(card.languages || []),
    ...(card.trackTitles || []),
  ].join(" ").toLowerCase();
  return words.every((word) => haystack.includes(word));
}

function renderLibrary() {
  const cards = state.cards;
  const matched = cards.filter((card) => cardMatches(card, state.query, state.author, state.category));
  const authors = uniqueValues(cards, "author");
  const categories = uniqueValues(cards, "category");
  const authorOptions = [`<option value="">All authors</option>`]
    .concat(authors.map((author) => `<option value="${escapeHtml(author)}"${author === state.author ? " selected" : ""}>${escapeHtml(author)}</option>`))
    .join("");
  const categoryOptions = [`<option value="">All categories</option>`]
    .concat(categories.map((category) => `<option value="${escapeHtml(category)}"${category === state.category ? " selected" : ""}>${escapeHtml(category)}</option>`))
    .join("");
  const tiles = matched.map((card) => {
    const category = (card.category || "").trim();
    const badge = category
      ? `<span class="badge ${accentFor(category)}">${escapeHtml(category)}</span>`
      : "";
    const duration = card.readableDuration
      ? `<span class="muted">${escapeHtml(card.readableDuration)}</span>`
      : "";
    return `
    <button type="button" class="card-tile" data-id="${escapeHtml(card.cardId)}">
      <span class="cover-frame">${coverMarkup(card, "cover")}</span>
      <span class="tile-meta">
        <strong>${escapeHtml(card.title)}</strong>
        <span class="author">${escapeHtml(card.author || "Unknown author")}</span>
        <span class="meta-row">
          <span class="audio-mark">${ICON_AUDIO}Audio</span>
          ${duration}
          ${badge}
        </span>
        ${backupMarkup(card)}
      </span>
    </button>`;
  }).join("");
  const countLabel = matched.length === cards.length
    ? `${cards.length} ${cards.length === 1 ? "card" : "cards"}`
    : `${matched.length} of ${cards.length}`;
  const chips = categories.length > 0 && categories.length <= 8
    ? `<div class="chips" role="group" aria-label="Category">${
      [`<button type="button" class="chip${state.category ? "" : " is-selected"}" data-category="" aria-pressed="${state.category ? "false" : "true"}">All</button>`]
        .concat(categories.map((category) => `<button type="button" class="chip${category === state.category ? " is-selected" : ""}" data-category="${escapeHtml(category)}" aria-pressed="${category === state.category ? "true" : "false"}">${escapeHtml(category)}</button>`))
        .join("")
    }</div>`
    : "";
  view.innerHTML = `
    <div class="toolbar">
      <div>
        <h2>Your library</h2>
        <p class="library-stats" id="library-count">${countLabel} · ${backupSummary(matched)}</p>
      </div>
    </div>
    <div class="filters">
      <label class="search-field">
        <input id="library-search" type="search" placeholder="Search your stories…" value="${escapeHtml(state.query)}" aria-label="Search the library">
        ${ICON_SEARCH}
      </label>
      <select id="library-author" aria-label="Filter by author">${authorOptions}</select>
      <select id="library-category" aria-label="Filter by category">${categoryOptions}</select>
    </div>
    ${chips}
    ${matched.length
      ? `<div class="grid">${tiles}</div>`
      : `<p class="muted">No cards match.</p>`}`;
  const search = document.querySelector("#library-search");
  search.addEventListener("input", () => {
    state.query = search.value;
    const position = search.selectionStart;
    renderLibrary();
    const next = document.querySelector("#library-search");
    next.focus();
    if (position !== null) next.setSelectionRange(position, position);
  });
  document.querySelector("#library-author").addEventListener("change", (event) => {
    state.author = event.target.value;
    renderLibrary();
  });
  document.querySelector("#library-category").addEventListener("change", (event) => {
    state.category = event.target.value;
    renderLibrary();
  });
  view.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.category = chip.dataset.category || "";
      renderLibrary();
    });
  });
  view.querySelectorAll(".card-tile").forEach((tile) => {
    tile.addEventListener("click", () => openCard(tile.dataset.id));
  });
}

async function loadLibrary() {
  view.innerHTML = `<div class="toolbar"><h2>Your library</h2><p class="muted">Loading your library…</p></div>`;
  try {
    state.cards = await api("/api/cards");
    if (!state.cards.length) {
      state.query = "";
      state.author = "";
      state.category = "";
      view.innerHTML = `
        <section class="empty">
          <h2>Your library is empty</h2>
          <p>Add your first card to start building your backup library.</p>
          <button type="button" class="primary" id="empty-add">Add card</button>
        </section>`;
      document.querySelector("#empty-add").addEventListener("click", () => show("add"));
      return;
    }
    renderLibrary();
  } catch (error) {
    view.innerHTML = `<p class="banner">${escapeHtml(error.message)}</p>`;
  }
}

function trackRow(track) {
  const number = `<span class="num">${escapeHtml(track.number)}</span>`;
  const title = `<span>${escapeHtml(track.title)}</span>`;
  const duration = `<span class="muted">${escapeHtml(track.readableDuration || "")}</span>`;
  return `${number}${title}${duration}`;
}

function startPlayer(card, playlist) {
  const audio = new Audio();
  audio.preload = "metadata";
  audio.hidden = true;
  state.audio = audio;
  document.querySelector(".player").append(audio);
  const title = document.querySelector("#player-title");
  const status = document.querySelector("#player-status");
  const toggle = document.querySelector("#player-toggle");
  const prev = document.querySelector("#player-prev");
  const next = document.querySelector("#player-next");
  const range = document.querySelector("#player-range");
  const current = document.querySelector("#player-current");
  const duration = document.querySelector("#player-duration");
  let index = -1;
  let scrubbing = false;

  function paintToggle() {
    const playing = state.audio === audio && !audio.paused;
    toggle.setAttribute("aria-label", playing ? "Pause" : "Play");
    toggle.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
  }

  function playAudio() {
    audio.play().catch((error) => {
      if (error && error.name === "AbortError") return;
      paintToggle();
    });
  }

  function highlight() {
    view.querySelectorAll(".track-play").forEach((row) => {
      const on = Number(row.dataset.index) === index;
      row.classList.toggle("is-current", on);
      if (on) row.setAttribute("aria-current", "true");
      else row.removeAttribute("aria-current");
    });
  }

  function updateSkip() {
    prev.disabled = index < 0;
    next.disabled = index < 0 || index >= playlist.length - 1;
  }

  function playIndex(nextIndex) {
    const track = playlist[nextIndex];
    if (!track || state.audio !== audio) return;
    if (nextIndex === index && audio.getAttribute("src")) {
      playAudio();
      return;
    }
    index = nextIndex;
    status.textContent = "";
    title.textContent = track.title || "Untitled";
    current.textContent = "0:00";
    range.value = "0";
    const known = Number(track.duration);
    if (Number.isFinite(known) && known > 0) {
      range.max = String(known);
      duration.textContent = formatClock(known);
    } else {
      range.max = "0";
      duration.textContent = "0:00";
    }
    range.disabled = true;
    highlight();
    updateSkip();
    audio.src = cardFileUrl(card.cardId, track.file);
    playAudio();
  }

  audio.addEventListener("play", paintToggle);
  audio.addEventListener("pause", paintToggle);
  audio.addEventListener("loadedmetadata", () => {
    if (state.audio !== audio) return;
    const length = Number.isFinite(audio.duration) ? audio.duration : 0;
    range.max = String(length);
    range.disabled = length <= 0;
    duration.textContent = formatClock(length);
  });
  audio.addEventListener("timeupdate", () => {
    if (state.audio !== audio || scrubbing) return;
    range.value = String(audio.currentTime || 0);
    current.textContent = formatClock(audio.currentTime);
  });
  audio.addEventListener("ended", () => {
    if (state.audio !== audio) return;
    if (index < playlist.length - 1) playIndex(index + 1);
    else paintToggle();
  });
  audio.addEventListener("error", () => {
    if (state.audio !== audio) return;
    status.textContent = "Could not play this track.";
    paintToggle();
  });

  toggle.addEventListener("click", () => {
    if (!playlist.length || state.audio !== audio) return;
    if (index < 0) {
      playIndex(0);
      return;
    }
    if (audio.paused) playAudio();
    else audio.pause();
  });
  prev.addEventListener("click", () => {
    if (index < 0 || state.audio !== audio) return;
    if (audio.currentTime > 3 || index === 0) {
      audio.currentTime = 0;
      range.value = "0";
      current.textContent = "0:00";
      return;
    }
    playIndex(index - 1);
  });
  next.addEventListener("click", () => {
    if (state.audio !== audio || index >= playlist.length - 1) return;
    playIndex(index + 1);
  });
  range.addEventListener("input", () => {
    scrubbing = true;
    const nextTime = Number(range.value);
    current.textContent = formatClock(nextTime);
    if (state.audio === audio && Number.isFinite(nextTime)) audio.currentTime = nextTime;
  });
  range.addEventListener("change", () => {
    scrubbing = false;
  });
  range.addEventListener("pointerup", () => {
    scrubbing = false;
  });
  view.querySelectorAll(".track-play").forEach((row) => {
    row.addEventListener("click", () => playIndex(Number(row.dataset.index)));
  });
}

async function openCard(cardId) {
  stopPlayback();
  state.cardId = cardId;
  navButtons.forEach((button) => button.classList.remove("is-active"));
  try {
    const card = await api(`/api/cards/${encodeURIComponent(cardId)}`);
    if (state.cardId !== cardId) return;
    const facts = [
      "Audio",
      card.author,
      card.category,
      card.readableDuration,
      card.trackCount ? `${card.trackCount} tracks` : "",
      (card.languages || []).join(", "),
    ].filter(Boolean);
    const playlist = [];
    const tracks = (card.chapters || []).map((chapter) => {
      const heading = chapter.title ? `<li class="chapter-label">${escapeHtml(chapter.title)}</li>` : "";
      const rows = (chapter.tracks || []).map((track) => {
        if (!track.file) return `<li class="track-missing">${trackRow(track)}</li>`;
        const index = playlist.length;
        playlist.push(track);
        return `<li><button type="button" class="track-play" data-index="${index}">${trackRow(track)}</button></li>`;
      }).join("");
      return heading + rows;
    }).join("");
    const playerTitle = playlist.length ? "Select a track" : "No audio on this card";
    view.innerHTML = `
      <button type="button" class="back" id="back">Back to library</button>
      <article class="detail-layout">
        <div class="cover-frame detail-frame">${coverMarkup(card, "detail-cover cover")}</div>
        <div class="detail-copy">
          <h2>${escapeHtml(card.title)}</h2>
          <div class="facts">${facts.map((fact) => `<span>${escapeHtml(fact)}</span>`).join("")}</div>
          ${card.description ? `<p class="description">${escapeHtml(card.description)}</p>` : ""}
          <div class="player">
            <p class="player-title" id="player-title">${escapeHtml(playerTitle)}</p>
            <div class="player-transport">
              <button type="button" class="player-btn" id="player-prev" aria-label="Previous track" disabled>${ICON_PREV}</button>
              <button type="button" class="player-btn player-toggle" id="player-toggle" aria-label="Play"${playlist.length ? "" : " disabled"}>${ICON_PLAY}</button>
              <button type="button" class="player-btn" id="player-next" aria-label="Next track" disabled>${ICON_NEXT}</button>
            </div>
            <div class="player-seek">
              <span id="player-current">0:00</span>
              <input id="player-range" type="range" min="0" max="0" value="0" step="0.1" aria-label="Seek" disabled>
              <span id="player-duration">0:00</span>
            </div>
            <p class="player-status" id="player-status"></p>
          </div>
          <ol class="tracks">${tracks}</ol>
        </div>
      </article>`;
    document.querySelector("#back").addEventListener("click", () => show("library"));
    if (playlist.length) startPlayer(card, playlist);
  } catch (error) {
    if (state.cardId !== cardId) return;
    view.innerHTML = `<p class="banner">${escapeHtml(error.message)}</p>`;
  }
}

function renderJob(job) {
  const total = job.total || 0;
  const finished = job.finished || 0;
  const width = total ? Math.round((finished / total) * 100) : 0;
  const logs = (job.logs || []).map((line) => {
    const cls = line.level === "error" ? "error" : "";
    return `<div class="${cls}">${escapeHtml(line.message)}</div>`;
  }).join("");
  const succeeded = (job.succeeded || []).map((item) => `<p class="ok">${escapeHtml(item.title)} saved</p>`).join("");
  const failed = (job.failed || []).map((item) => `<p class="bad">${escapeHtml(item.url)} — ${escapeHtml(item.error)}</p>`).join("");
  const skipped = (job.skipped || []).map((item) => `<p class="muted">${escapeHtml(item.title)} already in the library</p>`).join("");
  const summary = job.status === "done" ? `<div class="summary">${succeeded}${skipped}${failed}</div>` : "";
  const status = job.status === "running"
    ? `Downloading ${Math.min(finished + 1, total)} of ${total}`
    : "Finished";
  return `
    <p class="muted" id="job-status">${escapeHtml(status)}</p>
    <div class="progress" aria-hidden="true"><span style="width:${width}%"></span></div>
    ${summary}
    <div class="log" id="job-log">${logs}</div>`;
}

async function loadAdd() {
  stopJobPoll();
  view.innerHTML = `
    <section class="panel">
      <h2>Add cards</h2>
      <p class="muted">Paste one or more Yoto URLs, one per line. Each card stays in your library, and a zip copy is written to the backup folder. Only add cards you legally own, or cards you have permission to keep a copy of.</p>
      <form id="add-form">
        <div class="field">
          <label for="urls">Yoto URLs</label>
          <textarea id="urls" name="urls" placeholder="https://yoto.io/…"></textarea>
        </div>
        <label class="check">
          <input id="replace-existing" name="replace_existing" type="checkbox">
          Replace cards already in the library
        </label>
        <label class="check terms-check">
          <input id="confirm-ownership" name="confirm_ownership" type="checkbox" required>
          <span>I legally own these cards, or I have permission to keep a copy of them.</span>
        </label>
        <p class="terms-hint">The full terms are in <button type="button" class="text-link" id="read-terms">Settings</button>.</p>
        <button class="primary" type="submit">Download</button>
      </form>
      <div id="job"></div>
    </section>`;
  document.querySelector("#add-form").addEventListener("submit", startJob);
  document.querySelector("#read-terms").addEventListener("click", () => {
    show("settings");
    document.querySelector("#terms-heading")?.scrollIntoView({ block: "start" });
  });
  try {
    const current = await api("/api/jobs/current");
    if (current.status === "running") watchJob(current);
  } catch (_error) {
    // The form still works if the status check fails.
  }
}

async function startJob(event) {
  event.preventDefault();
  const urls = new FormData(event.target).get("urls") || "";
  if (!event.target.confirm_ownership.checked) {
    document.querySelector("#job").innerHTML = `<p class="banner">Confirm that you legally own these cards, or have permission to keep a copy, before downloading.</p>`;
    return;
  }
  const button = event.target.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls,
        replace_existing: Boolean(event.target.replace_existing.checked),
        confirm_ownership: true,
      }),
    });
    watchJob(job);
  } catch (error) {
    document.querySelector("#job").innerHTML = `<p class="banner">${escapeHtml(error.message)}</p>`;
    button.disabled = false;
  }
}

function watchJob(job) {
  paintJob(job);
  stopJobPoll();
  state.jobTimer = setInterval(async () => {
    try {
      const latest = await api(`/api/jobs/${job.id}`);
      paintJob(latest);
      if (latest.status === "done") stopJobPoll();
    } catch (error) {
      stopJobPoll();
      document.querySelector("#job").innerHTML = `<p class="banner">${escapeHtml(error.message)}</p>`;
    }
  }, 700);
}

function paintJob(job) {
  const slot = document.querySelector("#job");
  if (!slot) return;
  slot.innerHTML = renderJob(job);
  const log = document.querySelector("#job-log");
  if (log) log.scrollTop = log.scrollHeight;
  const button = document.querySelector("#add-form button[type='submit']");
  if (button) button.disabled = job.status === "running";
}

function stopJobPoll() {
  if (state.jobTimer) {
    clearInterval(state.jobTimer);
    state.jobTimer = null;
  }
}

async function loadSettings() {
  stopJobPoll();
  view.innerHTML = `
    <section class="panel">
      <h2>Settings</h2>
      <p class="muted">The library is the cards you browse. Backups are zip copies in a different folder.</p>
      <form id="settings-form">
        <div class="field">
          <label for="library_dir">Library folder</label>
          <input id="library_dir" name="library_dir" type="text" required>
        </div>
        <div class="field">
          <label for="backup_dir">Backup folder</label>
          <input id="backup_dir" name="backup_dir" type="text" required>
        </div>
        <button class="primary" type="submit">Save settings</button>
      </form>
      <div id="settings-note"></div>
      ${termsMarkup()}
    </section>`;
  const form = document.querySelector("#settings-form");
  try {
    const settings = await api("/api/settings");
    form.library_dir.value = settings.library_dir;
    form.backup_dir.value = settings.backup_dir;
  } catch (error) {
    document.querySelector("#settings-note").innerHTML = `<p class="banner">${escapeHtml(error.message)}</p>`;
  }
  form.addEventListener("submit", saveSettings);
}

async function loadCloud() {
  stopJobPoll();
  view.innerHTML = `
    <section class="panel">
      <h2>Cloud backup</h2>
      <p class="muted">Copy the library to a folder in your Google Drive, so it survives if this computer or server is lost. Backups run only when you start them. Cards that have not changed since the last backup are skipped.</p>
      <div class="cloud-status">
        <h3>Google Drive</h3>
        <p id="drive-state" class="muted">Checking Google Drive…</p>
        <div class="button-row">
          <button type="button" class="primary" id="drive-signin">Sign in with Google</button>
          <button type="button" class="primary" id="drive-backup" hidden>Back up now</button>
          <button type="button" class="ghost" id="drive-stop" hidden>Stop backup</button>
          <button type="button" class="ghost" id="drive-signout" hidden>Sign out</button>
        </div>
        <div id="drive-login"></div>
        <div id="drive-note"></div>
        <div id="drive-job"></div>
      </div>
      <details class="cloud-setup" id="drive-setup">
        <summary>Google Drive setup</summary>
        <form id="drive-form">
          <div id="drive-client">
            <p class="terms-hint">In Google Cloud Console, enable the Google Drive API and create an OAuth client of type <strong>TVs and Limited Input devices</strong>. Paste its client id and secret here.</p>
            <div class="field">
              <label for="drive_client_id">Google client id</label>
              <input id="drive_client_id" name="client_id" type="text" autocomplete="off" spellcheck="false">
            </div>
            <div class="field">
              <label for="drive_secret">Google client secret</label>
              <input id="drive_secret" name="client_secret" type="password" autocomplete="off">
              <p class="terms-hint" id="drive-secret-hint"></p>
            </div>
          </div>
          <p class="terms-hint" id="drive-client-env" hidden>The Google client is set by the server.</p>
          <div class="field">
            <label for="drive_folder">Google Drive folder</label>
            <input id="drive_folder" name="folder_name" type="text" required>
            <p class="terms-hint">YotoLib creates this folder in your Drive the first time it backs up. It can only see files it created.</p>
          </div>
          <button class="primary" type="submit">Save setup</button>
        </form>
      </details>
    </section>`;
  await loadDrive();
}

function stopDrivePoll() {
  if (state.driveTimer) {
    clearInterval(state.driveTimer);
    state.driveTimer = null;
  }
}

function driveNote(html) {
  const note = document.querySelector("#drive-note");
  if (note) note.innerHTML = html;
}

async function loadDrive() {
  const form = document.querySelector("#drive-form");
  form.addEventListener("submit", saveDriveSettings);
  document.querySelector("#drive-signin").addEventListener("click", signInDrive);
  document.querySelector("#drive-backup").addEventListener("click", backupToDrive);
  document.querySelector("#drive-stop").addEventListener("click", () => driveAction("/api/drive/backup", "DELETE"));
  document.querySelector("#drive-signout").addEventListener("click", signOutDrive);
  try {
    const status = await api("/api/drive");
    form.client_id.value = status.clientId || "";
    form.folder_name.value = status.folderName || "";
    document.querySelector("#drive-setup").open = !status.clientConfigured;
    state.drive = null;
    applyDrive(status);
  } catch (error) {
    driveNote(`<p class="banner">${escapeHtml(error.message)}</p>`);
  }
}

function applyDrive(status) {
  if (state.page !== "cloud") return;
  const previous = state.drive;
  state.drive = status;
  const login = status.login;
  const pending = Boolean(login && login.status === "pending");
  const running = status.backup.status === "running";

  document.querySelector("#drive-state").textContent = status.connected
    ? `Signed in${status.email ? ` as ${status.email}` : ""}. Backups go to ${status.folderName} on Google Drive.`
    : status.clientConfigured
      ? "Not signed in."
      : "Finish Google Drive setup below, then sign in.";
  document.querySelector("#drive-client").hidden = status.clientFromEnv;
  document.querySelector("#drive-client-env").hidden = !status.clientFromEnv;
  document.querySelector("#drive-secret-hint").textContent = status.secretSet
    ? "A client secret is saved. Leave this blank to keep it."
    : "";

  const signIn = document.querySelector("#drive-signin");
  signIn.hidden = status.connected;
  signIn.disabled = !status.clientConfigured || pending;
  const backup = document.querySelector("#drive-backup");
  backup.hidden = !status.connected || running;
  document.querySelector("#drive-stop").hidden = !running;
  const signOut = document.querySelector("#drive-signout");
  signOut.hidden = !status.connected;
  signOut.disabled = running;

  paintDriveLogin(login, previous && previous.login);
  paintDriveJob(status.backup);

  const wasPending = Boolean(previous && previous.login && previous.login.status === "pending");
  if (wasPending && !pending) {
    closeDrivePopup();
    if (login && login.status === "done") {
      driveNote(`<p class="ok">Signed in to Google Drive.</p>`);
    } else if (login && login.error) {
      driveNote(`<p class="banner">${escapeHtml(login.error)}</p>`);
    }
  }

  if (pending || running) {
    if (!state.driveTimer) state.driveTimer = setInterval(pollDrive, 2000);
  } else {
    stopDrivePoll();
  }
}

async function pollDrive() {
  try {
    applyDrive(await api("/api/drive"));
  } catch (error) {
    stopDrivePoll();
    driveNote(`<p class="banner">${escapeHtml(error.message)}</p>`);
  }
}

function paintDriveLogin(login, previous) {
  const slot = document.querySelector("#drive-login");
  if (!login || login.status !== "pending") {
    slot.innerHTML = "";
    return;
  }
  if (previous && previous.status === "pending" && previous.userCode === login.userCode && slot.innerHTML) return;
  const minutes = Math.max(1, Math.round(login.expiresIn / 60));
  slot.innerHTML = `
    <div class="drive-login">
      <p>In the Google window, enter this code and allow access:</p>
      <p class="drive-code">${escapeHtml(login.userCode)}</p>
      <p class="terms-hint">The code expires in about ${minutes} minutes. This page updates when you finish.</p>
      <div class="button-row">
        <button type="button" class="ghost" id="drive-copy">Copy code</button>
        <button type="button" class="ghost" id="drive-open">Open Google window</button>
        <button type="button" class="ghost" id="drive-cancel">Cancel</button>
      </div>
    </div>`;
  document.querySelector("#drive-copy").addEventListener("click", () => copyDriveCode(login.userCode));
  document.querySelector("#drive-open").addEventListener("click", () => openDrivePopup(login.verificationUrl));
  document.querySelector("#drive-cancel").addEventListener("click", async () => {
    closeDrivePopup();
    await driveAction("/api/drive/login", "DELETE");
    driveNote(`<p class="muted">Sign-in cancelled.</p>`);
  });
}

function paintDriveJob(backup) {
  const slot = document.querySelector("#drive-job");
  if (backup.status === "running") {
    const width = backup.total ? Math.round((backup.finished / backup.total) * 100) : 0;
    slot.innerHTML = `
      <div class="progress" aria-hidden="true"><span style="width:${width}%"></span></div>
      <p class="muted">${escapeHtml(backup.message || "Backing up…")} · ${backup.finished} of ${backup.total}</p>`;
  } else if (backup.status === "error") {
    slot.innerHTML = `<p class="banner">${escapeHtml(backup.error)}</p>`;
  } else if (backup.status === "done") {
    slot.innerHTML = `<p class="ok">${escapeHtml(backup.message)}</p>`;
  } else if (backup.status === "cancelled") {
    slot.innerHTML = `<p class="muted">${escapeHtml(backup.message)}</p>`;
  } else {
    slot.innerHTML = "";
  }
}

function openDrivePopup(url) {
  const popup = window.open(url || "", "yotolib-google", "popup,width=520,height=720");
  if (popup) state.drivePopup = popup;
  return popup;
}

function closeDrivePopup() {
  try {
    if (state.drivePopup && !state.drivePopup.closed) state.drivePopup.close();
  } catch (error) {
    // The window may already be gone.
  }
  state.drivePopup = null;
}

async function copyDriveCode(code) {
  try {
    await navigator.clipboard.writeText(code);
    driveNote(`<p class="muted">Code copied.</p>`);
  } catch (error) {
    driveNote(`<p class="muted">Select the code and copy it.</p>`);
  }
}

async function signInDrive() {
  driveNote("");
  // Open the window during the click so the browser does not block it,
  // then point it at Google once the code is ready.
  const popup = openDrivePopup("");
  try {
    if (popup) popup.document.title = "Opening Google…";
  } catch (error) {
    // Ignore: only cosmetic.
  }
  try {
    const status = await api("/api/drive/login", { method: "POST" });
    const login = status.login;
    if (popup) {
      popup.location.href = login.verificationUrl;
    } else {
      driveNote(`<p class="muted">Your browser blocked the window. Choose <strong>Open Google window</strong>.</p>`);
    }
    applyDrive(status);
    navigator.clipboard?.writeText(login.userCode).catch(() => {});
  } catch (error) {
    closeDrivePopup();
    driveNote(`<p class="banner">${escapeHtml(error.message)}</p>`);
  }
}

async function driveAction(path, method) {
  try {
    applyDrive(await api(path, { method }));
    return true;
  } catch (error) {
    driveNote(`<p class="banner">${escapeHtml(error.message)}</p>`);
    return false;
  }
}

async function backupToDrive() {
  driveNote("");
  await driveAction("/api/drive/backup", "POST");
}

async function signOutDrive() {
  if (await driveAction("/api/drive/logout", "POST")) {
    driveNote(`<p class="muted">Signed out of Google Drive.</p>`);
  }
}

async function saveDriveSettings(event) {
  event.preventDefault();
  const form = event.target;
  try {
    const status = await api("/api/drive", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: form.client_id.value,
        client_secret: form.client_secret.value,
        folder_name: form.folder_name.value,
      }),
    });
    form.client_secret.value = "";
    form.client_id.value = status.clientId || "";
    form.folder_name.value = status.folderName;
    applyDrive(status);
    driveNote(`<p class="ok">Drive settings saved.</p>`);
  } catch (error) {
    driveNote(`<p class="banner">${escapeHtml(error.message)}</p>`);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.target;
  const note = document.querySelector("#settings-note");
  try {
    const saved = await api("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        library_dir: form.library_dir.value,
        backup_dir: form.backup_dir.value,
      }),
    });
    form.library_dir.value = saved.library_dir;
    form.backup_dir.value = saved.backup_dir;
    note.innerHTML = `<p class="ok">Saved.</p>`;
  } catch (error) {
    note.innerHTML = `<p class="banner">${escapeHtml(error.message)}</p>`;
  }
}

show("home");
