/* Shared behaviour: API calls, speech, and the "Ask about accessibility" chat (bottom-left). */

export const API = (window.PARITY_API || "").replace(/\/$/, "");

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c.nodeType ? c : document.createTextNode(c));
  return node;
}

/** fetch JSON from the API; free hosting sleeps, so the first call can take ~a minute. */
export async function api(path, options = {}, onSlow) {
  const slow = onSlow ? setTimeout(onSlow, 4000) : null;
  try {
    const res = await fetch(API + path, { headers: { "content-type": "application/json" }, ...options });
    let body = null;
    try { body = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      const err = new Error((body && body.detail) || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return body;
  } catch (e) {
    if (e.status) throw e;
    const err = new Error("Couldn't reach the Parity server. It may be starting up (free hosting sleeps when idle); please try again in a minute.");
    err.status = 0;
    throw err;
  } finally {
    if (slow) clearTimeout(slow);
  }
}

/** Read text aloud with the browser's own speech engine (what a screen reader does, roughly). */
export function speak(text, button) {
  if (!("speechSynthesis" in window)) {
    if (button) button.textContent = "Speech isn't available in this browser";
    return;
  }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05;
  window.speechSynthesis.speak(u);
}

export function wireSpeakButtons(root = document) {
  root.querySelectorAll("[data-speak]").forEach((b) => b.addEventListener("click", () => speak(b.dataset.speak, b)));
}

/* ---------------------------------------------------------------- chat widget */

const SUGGESTED = [
  "How big do buttons need to be on mobile?",
  "What contrast does body text need?",
  "Do decorative images need alt text?",
  "Is a placeholder enough as a form label?",
];

export function mountChat() {
  const log = el("div", { class: "chat-log", role: "log", "aria-live": "polite", "aria-relevant": "additions" });
  const input = el("input", { id: "chat-q", type: "text", autocomplete: "off", maxlength: "500", placeholder: "e.g. Does a logo need alt text?" });
  const send = el("button", { type: "submit" }, "Ask");
  const form = el("form", { class: "chat-form" }, el("label", { for: "chat-q", class: "visually-hidden" }, "Your accessibility question"), input, send);
  const close = el("button", { class: "chat-close", type: "button", "aria-label": "Close assistant" }, "×");
  const panel = el("section", { class: "chat-panel", id: "chat-panel", "aria-labelledby": "chat-title", role: "dialog", "aria-modal": "false" },
    el("div", { class: "chat-top" },
      el("div", {}, el("h2", { id: "chat-title" }, "Ask about accessibility"),
        el("p", {}, "Answers come only from W3C's WCAG 2.2 text, with quotes checked word for word.")),
      close),
    log, form);
  const launch = el("button", { class: "chat-launch", type: "button", "aria-label": "Ask about accessibility (opens assistant)", "aria-expanded": "false", "aria-controls": "chat-panel" });
  launch.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg><span class="label-long" aria-hidden="true">Ask about accessibility</span>';
  document.body.append(panel, launch);
  // Full label at the top of the page; shrinks to an icon once you scroll, so it doesn't cover content.
  const compact = () => launch.classList.toggle("compact", window.scrollY > 240);
  window.addEventListener("scroll", compact, { passive: true });
  compact();

  const bot = (children, cls = "") => { const m = el("div", { class: `msg bot ${cls}` }, children); log.append(m); log.scrollTop = log.scrollHeight; return m; };
  bot(["Hi! I can explain any WCAG 2.2 rule in plain words. Try one of these:",
    el("div", { class: "suggestions", style: "margin-top:10px" }, SUGGESTED.map((q) => el("button", { type: "button", onclick: () => ask(q) }, q)))]);

  function open(state) {
    panel.classList.toggle("open", state);
    launch.setAttribute("aria-expanded", String(state));
    if (state) input.focus(); else launch.focus();
  }
  launch.addEventListener("click", () => open(!panel.classList.contains("open")));
  close.addEventListener("click", () => open(false));
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });

  async function ask(question) {
    log.append(el("div", { class: "msg user" }, question));
    const thinking = bot("Looking it up in WCAG 2.2…");
    send.disabled = true;
    try {
      const a = await api("/api/ask", { method: "POST", body: JSON.stringify({ question }) },
        () => { thinking.textContent = "Waking up the server (free hosting sleeps when idle). This can take up to a minute…"; });
      thinking.remove();
      const head = a.grounded
        ? el("div", { class: "verified" }, "✓ Verified against W3C text")
        : el("div", { class: "verified unverified" }, "Couldn't verify an answer");
      const quotes = (a.citations || []).map((c) => el("blockquote", {},
        el("strong", {}, `${c.sc} ${c.handle}: `), `“${c.quote}” `, el("a", { href: c.url, target: "_blank", rel: "noopener" }, "Read at W3C")));
      bot([head, el("div", {}, a.answer), ...quotes]);
    } catch (e) {
      thinking.remove();
      bot(e.message);
    } finally {
      send.disabled = false;
      log.scrollTop = log.scrollHeight;
    }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); const q = input.value.trim(); if (q.length >= 3) { input.value = ""; ask(q); } });
}

export function setGithubLinks() {
  document.querySelectorAll("[data-github]").forEach((a) => { a.href = window.PARITY_GITHUB; });
}
