// Sayt skripti: qorong'i rejim, tasdiqlash oynasi, real-time bildirishnoma va chat vidjeti.

// ---------- Qorong'i rejim ----------
const root = document.documentElement;
const mode = () => localStorage.getItem("theme") || root.dataset.defaultMode || "auto";
const applyTheme = () => {
  const m = mode();
  const dark = m === "dark" || (m === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
};
applyTheme();
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-theme-toggle]");
  if (!btn) return;
  localStorage.setItem("theme", root.classList.contains("dark") ? "light" : "dark");
  applyTheme();
});

// ---------- Tasdiqlash (data-confirm) ----------
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-close]");
  if (el) el.closest("[data-flash]")?.remove();
});

// ---------- Toast ----------
function toast(text, url) {
  let box = document.getElementById("toast-box");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast-box";
    box.className = "fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2";
    document.body.append(box);
  }
  const t = document.createElement(url ? "a" : "div");
  if (url) t.href = url;
  t.className = "card block p-3 text-sm shadow-lg ring-1 ring-primary-200 transition hover:-translate-y-0.5 dark:ring-primary-800";
  t.textContent = text;
  box.append(t);
  setTimeout(() => t.remove(), 6000);
}

function bump(selector) {
  document.querySelectorAll(selector).forEach((b) => {
    const n = (parseInt(b.textContent, 10) || 0) + 1;
    b.textContent = n;
    b.classList.remove("hidden");
  });
}

const wsUrl = (path) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;

// ---------- Foydalanuvchining shaxsiy real-time kanali ----------
function connectMe() {
  if (!document.body.dataset.auth) return;
  let retry = 1000;
  const open = () => {
    const ws = new WebSocket(wsUrl("/ws/me/"));
    ws.onopen = () => { retry = 1000; };
    ws.onmessage = (ev) => {
      const d = JSON.parse(ev.data);
      if (d.kind === "notification") { bump("[data-notif-badge]"); toast(d.text, d.url); }
      if (d.kind === "chat") {
        const here = document.querySelector(`[data-chat][data-room="${d.room}"]`);
        if (!here) { bump("[data-msg-badge]"); toast(`${d.sender}: ${d.preview}`, d.url); }
      }
    };
    ws.onclose = (ev) => { if (ev.code !== 4401) setTimeout(open, (retry = Math.min(retry * 2, 20000))); };
  };
  open();
}

// ---------- Chat vidjeti ----------
function initChat(box) {
  const room = box.dataset.room, me = parseInt(box.dataset.me, 10);
  const list = box.querySelector("[data-chat-list]"), form = box.querySelector("form");
  const input = form.querySelector("textarea"), status = box.querySelector("[data-chat-status]");
  const seen = new Set();
  let lastId = 0, lastDate = "", ws = null, poll = null, retry = 1000;

  const setStatus = (online) => {
    if (!status) return;
    status.textContent = online ? "● real-time" : "○ qayta ulanmoqda…";
    status.className = "text-xs " + (online ? "text-emerald-600" : "text-amber-600");
  };
  const scroll = () => { list.scrollTop = list.scrollHeight; };

  function add(m) {
    if (seen.has(m.id)) return;
    seen.add(m.id);
    lastId = Math.max(lastId, m.id);
    if (m.date !== lastDate) {
      lastDate = m.date;
      const d = document.createElement("div");
      d.className = "self-center rounded-full bg-slate-200 px-3 py-0.5 text-[11px] text-slate-600 dark:bg-slate-700 dark:text-slate-300";
      d.textContent = m.date;
      list.append(d);
    }
    const mine = m.sender_id === me;
    const b = document.createElement("div");
    b.className = "bubble " + (mine ? "bubble-me" : "bubble-other");
    if (!mine) {
      const n = document.createElement("div");
      n.className = "mb-0.5 text-xs font-semibold opacity-80";
      n.textContent = m.sender_name + (m.sender_role !== "student" ? " · " + (m.sender_role === "admin" ? "admin" : "o'qituvchi") : "");
      b.append(n);
    }
    const t = document.createElement("div");
    t.textContent = m.body;            // textContent — HTML kiritishdan himoya
    const meta = document.createElement("div");
    meta.className = "bubble-meta";
    meta.textContent = m.time;
    b.append(t, meta);
    list.append(b);
    scroll();
  }

  async function catchUp() {
    try {
      const r = await fetch(`${box.dataset.history}?after=${lastId || 0}`, { credentials: "same-origin" });
      if (r.ok) (await r.json()).messages.forEach(add);
    } catch (e) { /* tarmoq xatosi — keyingi urinishda */ }
  }
  const startPolling = () => { if (!poll) poll = setInterval(catchUp, 3000); };
  const stopPolling = () => { clearInterval(poll); poll = null; };

  function connect() {
    ws = new WebSocket(wsUrl(`/ws/chat/${room}/`));
    ws.onopen = () => { retry = 1000; setStatus(true); stopPolling(); catchUp(); };
    ws.onmessage = (ev) => {
      const d = JSON.parse(ev.data);
      if (d.type === "message") add(d);
      if (d.type === "error") toast(d.error);
    };
    ws.onclose = (ev) => {
      setStatus(false);
      startPolling();
      if (ev.code !== 4403) setTimeout(connect, (retry = Math.min(retry * 2, 20000)));
    };
  }

  async function send() {
    const body = input.value.trim();
    if (!body) return;
    input.value = "";
    if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify({ body })); return; }
    // WebSocket ishlamasa — oddiy HTTP orqali (zaxira yo'l)
    const fd = new FormData();
    fd.append("body", body);
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    const r = await fetch(box.dataset.send, { method: "POST", body: fd, headers: { "X-CSRFToken": csrf }, credentials: "same-origin" });
    const d = await r.json();
    if (r.ok) add(d.message); else toast(d.error || "Xabar yuborilmadi");
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); send(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });

  catchUp().then(() => { scroll(); input.focus({ preventScroll: true }); });
  connect();
}

document.addEventListener("DOMContentLoaded", () => {
  connectMe();
  document.querySelectorAll("[data-chat]").forEach(initChat);
});
