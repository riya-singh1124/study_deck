// Study Desk — vanilla JS frontend. JWT lives in localStorage.

const API = localStorage.getItem("study_desk_api") || "http://localhost:8000";
const TOKEN_KEY = "study_desk_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || null,
  user: null,
  decks: [],
  currentDeckId: null,
  currentCards: [],
  authMode: "login",
};

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  if (opts.body && !(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Session expired — please log in again");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

const authView = document.getElementById("auth-view");
const appView = document.getElementById("app-view");
const authForm = document.getElementById("auth-form");
const authError = document.getElementById("auth-error");
const authTitle = document.getElementById("auth-title");
const authSub = document.getElementById("auth-sub");
const authSubmit = document.getElementById("auth-submit");
const authToggle = document.getElementById("auth-toggle");
const authWrap = document.getElementById("auth-wrap");
const ctaSignup = document.getElementById("cta-signup");
const ctaLogin = document.getElementById("cta-login");

function setAuthMode(mode) {
  state.authMode = mode;
  if (mode === "signup") {
    authTitle.textContent = "Create your account";
    authSub.textContent = "Start building decks in seconds.";
    authSubmit.textContent = "Get started";
    authToggle.textContent = "Already have an account? Sign in";
  } else {
    authTitle.textContent = "Welcome back";
    authSub.textContent = "Sign in to keep learning.";
    authSubmit.textContent = "Sign in";
    authToggle.textContent = "Need an account? Sign up";
  }
  authError.textContent = "";
  authWrap.classList.remove("hidden");
  authWrap.scrollIntoView({ behavior: "smooth", block: "center" });
}

ctaSignup.addEventListener("click", () => setAuthMode("signup"));
if (ctaLogin) ctaLogin.addEventListener("click", () => setAuthMode("login"));
document.getElementById("cta-signup-nav").addEventListener("click", () => setAuthMode("signup"));
document.getElementById("cta-login-nav").addEventListener("click", () => setAuthMode("login"));
document.getElementById("cta-signup-stats").addEventListener("click", () => setAuthMode("signup"));
document.getElementById("cta-signup-bottom").addEventListener("click", () => setAuthMode("signup"));

// Goals tabs
document.querySelectorAll(".goal-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const key = tab.dataset.goal;
    document.querySelectorAll(".goal-tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".goal-panel").forEach((p) =>
      p.classList.toggle("active", p.dataset.goal === key)
    );
  });
});

authToggle.addEventListener("click", (e) => {
  e.preventDefault();
  setAuthMode(state.authMode === "login" ? "signup" : "login");
});

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.textContent = "";
  const email = authForm.email.value.trim();
  const password = authForm.password.value;
  try {
    let token;
    if (state.authMode === "signup") {
      const data = await api("/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      token = data.access_token;
    } else {
      const form = new FormData();
      form.append("username", email);
      form.append("password", password);
      const res = await fetch(`${API}/auth/login`, { method: "POST", body: form });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "Login failed");
      }
      const data = await res.json();
      token = data.access_token;
    }
    state.token = token;
    localStorage.setItem(TOKEN_KEY, token);
    await bootstrap();
  } catch (err) {
    authError.textContent = err.message;
  }
});

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  state.token = null;
  state.user = null;
  state.decks = [];
  state.currentDeckId = null;
  authView.classList.remove("hidden");
  appView.classList.add("hidden");
  document.getElementById("user-bar").innerHTML = "";
}

async function bootstrap() {
  if (!state.token) {
    authView.classList.remove("hidden");
    appView.classList.add("hidden");
    return;
  }
  try {
    state.user = await api("/me");
  } catch {
    return;
  }
  authView.classList.add("hidden");
  appView.classList.remove("hidden");
  document.getElementById("user-bar").innerHTML =
    `<span class="email">${escapeHtml(state.user.email)}</span> <button id="logout-btn" class="btn subtle">Log out</button>`;
  document.getElementById("logout-btn").addEventListener("click", logout);
  await loadDecks();
}

async function loadDecks() {
  state.decks = await api("/decks");
  renderDeckList();
  if (state.currentDeckId && state.decks.find((d) => d.id === state.currentDeckId)) {
    await openDeck(state.currentDeckId);
  } else {
    state.currentDeckId = null;
    document.getElementById("deck-detail").innerHTML = `
      <div class="empty">
        <div class="grad-orb"></div>
        <h3>No deck selected</h3>
        <p class="muted">Create your first deck or pick one from the left.</p>
      </div>`;
  }
}

function renderDeckList() {
  const ul = document.getElementById("decks");
  ul.innerHTML = "";
  if (state.decks.length === 0) {
    ul.innerHTML = `<li class="muted" style="cursor:default">No decks yet.</li>`;
    return;
  }
  for (const d of state.decks) {
    const li = document.createElement("li");
    if (d.id === state.currentDeckId) li.classList.add("active");
    const mine = d.owner_id === state.user.id;
    const chip = mine
      ? (d.is_public ? '<span class="chip">public</span>' : "")
      : '<span class="chip">shared</span>';
    li.innerHTML = `<span>${escapeHtml(d.title)}</span> ${chip}`;
    li.addEventListener("click", () => openDeck(d.id));
    ul.appendChild(li);
  }
}

document.getElementById("new-deck-btn").addEventListener("click", () => {
  showModal("New deck", `
    <label>Title <input id="m-title" required /></label>
    <label>Description <textarea id="m-desc"></textarea></label>
    <label><input type="checkbox" id="m-public" /> Public (anyone with account can view)</label>
  `, async () => {
    const title = document.getElementById("m-title").value.trim();
    if (!title) throw new Error("Title required");
    const body = {
      title,
      description: document.getElementById("m-desc").value,
      is_public: document.getElementById("m-public").checked,
    };
    const deck = await api("/decks", { method: "POST", body: JSON.stringify(body) });
    state.currentDeckId = deck.id;
    await loadDecks();
  });
});

async function openDeck(id) {
  state.currentDeckId = id;
  renderDeckList();
  const deck = state.decks.find((d) => d.id === id);
  if (!deck) return;
  state.currentCards = await api(`/decks/${id}/cards`);
  renderDeckDetail(deck);
}

function renderDeckDetail(deck) {
  const el = document.getElementById("deck-detail");
  const mine = deck.owner_id === state.user.id;
  const ownerActions = mine ? `
    <button data-act="add-card" class="btn primary">+ Card</button>
    <button data-act="share" class="btn ghost">Share</button>
    <button data-act="edit" class="btn ghost">Edit</button>
    <button data-act="delete" class="btn danger">Delete</button>
  ` : "";
  el.innerHTML = `
    <div class="deck-header">
      <div>
        <h2>${escapeHtml(deck.title)}</h2>
        <p class="meta">by ${escapeHtml(deck.owner_email)} · ${deck.card_count} card${deck.card_count === 1 ? "" : "s"}${deck.is_public ? " · public" : ""}</p>
        ${deck.description ? `<p class="desc">${escapeHtml(deck.description)}</p>` : ""}
      </div>
      <div class="actions">${ownerActions}</div>
    </div>
    <div id="cards-container"></div>
  `;
  renderCards(deck);
  el.querySelectorAll(".actions button").forEach((btn) => {
    btn.addEventListener("click", () => handleDeckAction(btn.dataset.act, deck));
  });
}

function renderCards(deck) {
  const container = document.getElementById("cards-container");
  container.innerHTML = "";
  if (state.currentCards.length === 0) {
    container.innerHTML = `<p class="muted">No cards yet. Add your first one!</p>`;
    return;
  }
  const mine = deck.owner_id === state.user.id;
  for (const c of state.currentCards) {
    const div = document.createElement("div");
    div.className = "card-item";
    div.innerHTML = `
      <p class="q">Question</p>
      <h4>${escapeHtml(c.question)}</h4>
      ${c.answer ? `<p class="a"><b>A:</b> ${escapeHtml(c.answer)}</p>` : ""}
      ${c.code ? `<pre>${escapeHtml(c.code)}</pre>` : ""}
      ${c.equation ? `<div class="eq">${escapeHtml(c.equation)}</div>` : ""}
      ${mine ? `<div class="card-actions">
        <button data-act="edit-card" data-id="${c.id}" class="btn ghost">Edit</button>
        <button data-act="del-card" data-id="${c.id}" class="btn danger">Delete</button>
      </div>` : ""}
    `;
    container.appendChild(div);
  }
  container.querySelectorAll("button[data-act='edit-card']").forEach((b) =>
    b.addEventListener("click", () => editCard(b.dataset.id))
  );
  container.querySelectorAll("button[data-act='del-card']").forEach((b) =>
    b.addEventListener("click", () => deleteCard(b.dataset.id))
  );
}

async function handleDeckAction(action, deck) {
  if (action === "add-card") return addCard(deck);
  if (action === "share") return shareDeck(deck);
  if (action === "edit") return editDeck(deck);
  if (action === "delete") return deleteDeck(deck);
}

function cardFormHtml(c = {}) {
  return `
    <label>Question <textarea id="m-q" required>${escapeHtml(c.question || "")}</textarea></label>
    <label>Answer <textarea id="m-a">${escapeHtml(c.answer || "")}</textarea></label>
    <label>Code <textarea id="m-code">${escapeHtml(c.code || "")}</textarea></label>
    <label>Equation <input id="m-eq" value="${escapeHtml(c.equation || "")}" /></label>
  `;
}

function readCardForm() {
  const q = document.getElementById("m-q").value.trim();
  if (!q) throw new Error("Question required");
  return {
    question: q,
    answer: document.getElementById("m-a").value,
    code: document.getElementById("m-code").value,
    equation: document.getElementById("m-eq").value,
  };
}

function addCard(deck) {
  showModal("New card", cardFormHtml(), async () => {
    const body = readCardForm();
    await api(`/decks/${deck.id}/cards`, { method: "POST", body: JSON.stringify(body) });
    await openDeck(deck.id);
    await loadDecks();
  });
}

function editCard(cardId) {
  const c = state.currentCards.find((x) => x.id === cardId);
  if (!c) return;
  showModal("Edit card", cardFormHtml(c), async () => {
    const body = readCardForm();
    await api(`/cards/${cardId}`, { method: "PATCH", body: JSON.stringify(body) });
    await openDeck(state.currentDeckId);
  });
}

async function deleteCard(cardId) {
  if (!confirm("Delete this card?")) return;
  await api(`/cards/${cardId}`, { method: "DELETE" });
  await openDeck(state.currentDeckId);
  await loadDecks();
}

function editDeck(deck) {
  showModal("Edit deck", `
    <label>Title <input id="m-title" value="${escapeHtml(deck.title)}" required /></label>
    <label>Description <textarea id="m-desc">${escapeHtml(deck.description || "")}</textarea></label>
    <label><input type="checkbox" id="m-public" ${deck.is_public ? "checked" : ""} /> Public</label>
  `, async () => {
    const body = {
      title: document.getElementById("m-title").value.trim(),
      description: document.getElementById("m-desc").value,
      is_public: document.getElementById("m-public").checked,
    };
    await api(`/decks/${deck.id}`, { method: "PATCH", body: JSON.stringify(body) });
    await loadDecks();
  });
}

async function deleteDeck(deck) {
  if (!confirm(`Delete deck "${deck.title}" and all its cards?`)) return;
  await api(`/decks/${deck.id}`, { method: "DELETE" });
  state.currentDeckId = null;
  await loadDecks();
}

function shareDeck(deck) {
  const current = deck.shared_with.length
    ? `<p class="muted">Currently shared with: ${deck.shared_with.map(escapeHtml).join(", ")}</p>`
    : "";
  showModal("Share deck", `
    ${current}
    <label>Email to share with <input id="m-email" type="email" required /></label>
  `, async () => {
    const email = document.getElementById("m-email").value.trim();
    await api(`/decks/${deck.id}/share`, { method: "POST", body: JSON.stringify({ email }) });
    await loadDecks();
  });
}

const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
let searchTimer = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (!q) {
    searchResults.classList.add("hidden");
    return;
  }
  searchTimer = setTimeout(async () => {
    try {
      const hits = await api(`/search?q=${encodeURIComponent(q)}`);
      renderSearch(hits);
    } catch (err) {
      searchResults.classList.remove("hidden");
      searchResults.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
    }
  }, 200);
});

function renderSearch(hits) {
  searchResults.classList.remove("hidden");
  if (hits.length === 0) {
    searchResults.innerHTML = `<p class="muted">No results.</p>`;
    return;
  }
  const items = hits.map((h) => `
    <li data-deck="${h.deck_id}">
      <span class="kind">${h.kind}</span>
      <b>${escapeHtml(h.deck_title)}</b>
      — ${escapeHtml(h.snippet)}
    </li>
  `).join("");
  searchResults.innerHTML = `<ul>${items}</ul>`;
  searchResults.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => {
      openDeck(li.dataset.deck);
      searchResults.classList.add("hidden");
      searchInput.value = "";
    });
  });
}

const modal = document.getElementById("modal");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalOk = document.getElementById("modal-ok");
const modalCancel = document.getElementById("modal-cancel");
let modalHandler = null;

function showModal(title, bodyHtml, onOk) {
  modalTitle.textContent = title;
  modalBody.innerHTML = `<div class="error" id="modal-error"></div>${bodyHtml}`;
  modalHandler = onOk;
  modal.classList.remove("hidden");
}
function hideModal() {
  modal.classList.add("hidden");
  modalBody.innerHTML = "";
  modalHandler = null;
}
modalCancel.addEventListener("click", hideModal);
modalOk.addEventListener("click", async () => {
  if (!modalHandler) return hideModal();
  const err = document.getElementById("modal-error");
  err.textContent = "";
  try {
    await modalHandler();
    hideModal();
  } catch (e) {
    err.textContent = e.message;
  }
});

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

bootstrap();
