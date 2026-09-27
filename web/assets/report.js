import { API, api, el, mountChat, setGithubLinks } from "./site.js";
import { CONFIDENCE, describe, IMPACT, PEOPLE } from "./explain.js";

setGithubLinks();
mountChat();

const app = document.getElementById("app");
const params = new URLSearchParams(location.search);
const WEIGHT = { critical: 3, serious: 2, moderate: 1, minor: 0.5, unknown: 0.5 };

function setStatus(children) {
  app.replaceChildren(el("div", { class: "wrap" }, el("div", { class: "status-box", role: "status" }, children)));
}

/* ---------------------------------------------------------------- loading */

async function loadExample(name) {
  const safe = name.replace(/[^a-z0-9-]/gi, "");
  const res = await fetch(`examples/${safe}/report.json`);
  if (!res.ok) throw new Error("That example report doesn't exist.");
  return res.json();
}

const STEPS = [
  [0, "Opening the page in a real browser (desktop and mobile)"],
  [8, "Running the accessibility rules"],
  [18, "Measuring text contrast over images"],
  [30, "Pressing Tab through the page like a keyboard user"],
  [40, "Looking at every image with the vision model"],
];

async function pollScan(id) {
  const started = Date.now();
  for (;;) {
    let job;
    try {
      job = await api(`/api/scans/${encodeURIComponent(id)}`);
    } catch (e) {
      setStatus([el("h1", {}, "We couldn't load this scan"), el("p", {}, e.message),
        el("p", {}, el("a", { href: "report.html?example=mars" }, "See an example report instead"))]);
      return null;
    }
    if (job.status === "done") return job.report;
    if (job.status === "blocked" || job.status === "failed") {
      const title = job.status === "blocked" ? "This site blocked the scan" : "The scan didn't finish";
      setStatus([el("h1", {}, title), el("p", {}, job.error || "Something went wrong."),
        job.status === "blocked" ? el("p", { class: "muted" }, "Many sites use bot protection. Parity never tries to get around it; the site owner can allow Parity's scanner.") : null,
        el("p", {}, el("a", { class: "btn btn-ghost", href: "index.html" }, "Try another page"), " ",
          el("a", { href: "report.html?example=mars" }, "or see an example report"))]);
      return null;
    }
    const secs = Math.round((Date.now() - started) / 1000);
    const heading = job.status === "queued" && job.position > 1
      ? `You're number ${job.position} in line`
      : "Scanning your page…";
    setStatus([
      el("h1", {}, heading),
      el("p", { class: "report-url" }, job.url),
      el("p", { class: "muted" }, `Usually 30–90 seconds. ${secs}s so far. You can keep this tab open; results stay available for an hour.`),
      el("ol", { class: "progress-list", "aria-label": "Typical scan steps" },
        STEPS.map(([t, label], i) => {
          const next = STEPS[i + 1] ? STEPS[i + 1][0] : Infinity;
          const cls = job.status === "queued" ? "" : secs >= next ? "done" : secs >= t ? "now" : "";
          return el("li", { class: cls }, el("span", { class: "dot", "aria-hidden": "true" }), label);
        })),
    ]);
    await new Promise((r) => setTimeout(r, 2500));
  }
}

/* ---------------------------------------------------------------- rendering */

function badge(kind, key) {
  const map = kind === "confidence" ? CONFIDENCE : IMPACT;
  const v = map[key] || { label: key, cls: "b-minor" };
  const icon = kind === "confidence" ? { "auto-verified": "✓ ", "ai-high-confidence": "◆ ", "needs-review": "? " }[key] || "" : "";
  return el("span", { class: `badge ${v.cls}`, title: v.help || "" }, icon + v.label);
}

function shotUrl(snap) {
  if (!snap || !snap.screenshot_url) return null;
  return snap.screenshot_url.startsWith("/api/") ? API + snap.screenshot_url : snap.screenshot_url;
}

function plainSummary(groups, report) {
  const claimed = groups.filter((g) => g.f.confidence !== "needs-review");
  const places = claimed.reduce((n, g) => n + g.f.nodes.length, 0);
  const people = new Map();
  claimed.forEach((g) => g.d.who.filter((w) => w !== "everyone").forEach((w) => people.set(w, (people.get(w) || 0) + 1)));
  const topPeople = [...people.entries()].sort((a, b) => b[1] - a[1]).slice(0, 2).map(([w]) => PEOPLE[w].label.toLowerCase());
  const biggest = claimed.filter((g) => g.f.wcag_criteria.length).slice(0, 2).map((g) => g.d.title.toLowerCase());
  if (!claimed.length) {
    return "Parity found no problems it can detect automatically. That's a great sign, but automated checks can't prove full accessibility, so a quick test with a screen reader and a keyboard is still worth it.";
  }
  return `Parity found ${claimed.length} kinds of problems across ${places} places on this page. ` +
    (biggest.length ? `The biggest: ${biggest.join(" and ")}. ` : "") +
    (topPeople.length ? `The people most affected are ${topPeople.join(" and ")}.` : "");
}

function render(report) {
  // Older reports recorded positions for hidden carousel slides (negative y): no pin beats a wrong pin.
  for (const f of report.findings) for (const n of f.nodes) {
    if (n.box && (n.box.y < 0 || n.box.x < 0 || n.box.width < 2 || n.box.height < 2)) delete n.box;
  }
  const desktop = report.snapshots.find((s) => s.viewport === "desktop") || report.snapshots[0];
  // Order: places affected x severity; unsure items and best practices (no WCAG rule) sink.
  const groups = report.findings.map((f) => ({ f, d: describe(f),
    w: f.nodes.length * (WEIGHT[f.impact] || 0.5) * (f.confidence === "needs-review" ? 0.2 : 1) * ((f.wcag_criteria || []).length ? 1 : 0.25) }))
    .sort((a, b) => b.w - a.w)
    .map((g, i) => ({ ...g, n: i + 1 }));
  const count = (pred) => groups.filter((g) => pred(g.f)).reduce((n, g) => n + g.f.nodes.length, 0);
  document.title = `${desktop?.title || report.url} · Accessibility report · Parity`;

  // ---- header
  const scanned = new Date(report.scanned_at);
  const head = el("div", { class: "report-head" }, el("div", { class: "wrap" },
    el("p", { class: "eyebrow" }, "Accessibility report"),
    el("h1", {}, desktop?.title || "Scanned page"),
    el("p", { class: "report-url" }, el("a", { href: report.url, rel: "noopener", target: "_blank" }, report.url)),
    el("p", { class: "report-meta" },
      el("span", {}, `Scanned ${scanned.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`),
      el("span", {}, `Desktop and mobile`),
      el("span", {}, `Checks: ${checkNames(report).join(" · ")}`)),
    el("p", { style: "font-size:1.15rem;max-width:46em;margin-top:18px" }, plainSummary(groups, report)),
    el("div", { class: "summary" },
      kpi(groups.filter((g) => g.f.confidence !== "needs-review").length, "kinds of problems"),
      kpi(count((f) => f.confidence !== "needs-review"), "places on the page affected"),
      kpi((report.resolved || []).length, "unclear cases settled by measuring"),
      kpi(count((f) => f.confidence === "needs-review"), "places left for a quick human check")),
    el("p", { style: "margin-top:18px" }, el("button", { class: "btn btn-ghost", type: "button", onclick: () => download(report) }, "Download the full data (JSON)"))));

  // ---- screenshot with pins
  const shotImg = el("img", { alt: `Screenshot of ${desktop?.title || "the page"} with numbered markers on each problem.`, src: shotUrl(desktop) || "" });
  const inner = el("div", { class: "shot-inner" }, shotImg);
  const frame = el("div", { class: "shot-frame", tabindex: "0", role: "region", "aria-label": "Page screenshot (scrollable)" }, inner);
  const hasBoxes = groups.some((g) => g.f.nodes.some((n) => n.box));
  const note = el("p", { class: "shot-note" }, hasBoxes
    ? "Numbers match the problems on the right. Select a number, or “Show it” on any element."
    : "This report was made before Parity recorded element positions, so the screenshot has no markers.");
  let current = "desktop";
  const tabs = el("div", { class: "shot-tabs", role: "group", "aria-label": "Screenshot" },
    report.snapshots.map((s) => el("button", { type: "button", "aria-pressed": String(s.viewport === "desktop"), onclick: (e) => switchShot(s, e.currentTarget) },
      s.viewport === "desktop" ? "Desktop" : "Mobile")));
  function switchShot(snap, btn) {
    current = snap.viewport;
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    shotImg.src = shotUrl(snap) || "";
    inner.querySelectorAll(".pin, .hl-box").forEach((p) => { p.hidden = current !== "desktop"; });
    note.hidden = current !== "desktop";
  }

  function naturalSize() {
    const s = desktop.screenshot_size;
    return s ? { w: s[0], h: s[1] } : { w: shotImg.naturalWidth || 1366, h: shotImg.naturalHeight || 1000 };
  }
  function placePins() {
    inner.querySelectorAll(".pin").forEach((p) => p.remove());
    const { w, h } = naturalSize();
    const scale = (inner.clientWidth || w) / w;  // screenshot pixels -> pixels on screen
    const GAP = 32;  // pins are 28px: keep them apart so each stays a comfortable tap target (WCAG 2.5.8)
    const placed = [];
    for (const g of groups) {
      const node = g.f.nodes.find((n) => n.box);
      if (!node || g.f.confidence === "needs-review") continue;
      let x = (node.box.x + Math.min(node.box.width, 40) / 2) * scale;
      let y = (node.box.y + Math.min(node.box.height, 40) / 2) * scale;
      x = Math.min(Math.max(x, 16), w * scale - 16);
      y = Math.max(y, 16);
      // Nudge down until it no longer overlaps an earlier pin (found by Parity auditing this page).
      for (let tries = 0; tries < 40 && placed.some((p) => Math.abs(p.x - x) < GAP && Math.abs(p.y - y) < GAP); tries++) y += GAP;
      placed.push({ x, y });
      const pin = el("button", {
        class: `pin p-${g.f.impact}`, type: "button", "data-n": g.n,
        style: `left:${(x / scale / w) * 100}%;top:${(y / scale / h) * 100}%`,
        "aria-label": `Problem ${g.n}: ${g.d.title}`,
        onclick: () => activate(g.n, true),
      }, String(g.n));
      pin.hidden = current !== "desktop";
      inner.append(pin);
    }
  }
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => hasBoxes && placePins(), 150); });
  if (hasBoxes) (shotImg.complete ? placePins() : shotImg.addEventListener("load", placePins, { once: true }));

  function highlight(node) {
    inner.querySelectorAll(".hl-box").forEach((b) => b.remove());
    if (!node.box || current !== "desktop") return;
    const { w, h } = naturalSize();
    const box = el("div", { class: "hl-box", style: `left:${node.box.x / w * 100}%;top:${node.box.y / h * 100}%;width:${Math.max(node.box.width, 6) / w * 100}%;height:${Math.max(node.box.height, 6) / h * 100}%` });
    inner.append(box);
    const scale = inner.clientWidth / w;
    frame.scrollTo({ top: Math.max(0, node.box.y * scale - frame.clientHeight / 3), behavior: "smooth" });
  }

  // ---- findings
  const list = el("div", { id: "findings" });
  function activate(n, fromPin) {
    list.querySelectorAll(".finding").forEach((c) => c.classList.toggle("is-active", c.dataset.n === String(n)));
    inner.querySelectorAll(".pin").forEach((p) => p.classList.toggle("is-active", p.dataset.n === String(n)));
    const g = groups.find((x) => x.n === n);
    const node = g && g.f.nodes.find((x) => x.box);
    if (node) highlight(node);
    if (fromPin) {
      const card = list.querySelector(`[data-n="${n}"]`);
      card.scrollIntoView({ behavior: "smooth", block: "start" });
      card.querySelector("h3").focus({ preventScroll: true });
    }
  }

  function findingCard(g) {
    const { f, d } = g;
    const cite = f.citations && f.citations[0];
    const elements = f.nodes.map((n) => el("div", { class: "el" },
      el("code", {}, n.html.length > 160 ? n.html.slice(0, 160) + "…" : n.html),
      n.evidence ? el("p", { class: "evidence" }, n.evidence) : (n.failure_summary ? el("p", { class: "evidence muted" }, n.failure_summary.replace(/^Fix (any|all) of the following:\s*/i, "")) : null),
      n.suggestion ? el("p", { class: "fix" }, el("strong", {}, "Suggested fix: "), n.suggestion) : null,
      n.box ? el("button", { class: "locate", type: "button", onclick: () => { activate(g.n); highlight(n); } }, "Show it on the screenshot") : null));
    return el("article", { class: "finding", "data-n": g.n, "data-conf": f.confidence, "aria-labelledby": `f${g.n}` },
      el("div", { class: "finding-head" },
        el("span", { class: `finding-num p-${f.impact}`, "aria-hidden": "true" }, String(g.n)),
        el("div", {},
          el("h3", { id: `f${g.n}`, tabindex: "-1" }, el("span", { class: "visually-hidden" }, `Problem ${g.n}: `), d.title),
          el("div", { class: "badges" }, badge("impact", f.impact), badge("confidence", f.confidence),
            el("span", { class: "badge b-minor" }, `${f.nodes.length} ${f.nodes.length === 1 ? "place" : "places"}`),
            f.viewports.length === 1 ? el("span", { class: "badge b-minor" }, `${f.viewports[0]} only`) : null))),
      el("div", { class: "finding-body" },
        el("p", { class: "why" }, d.what),
        el("div", { class: "who-row" }, d.who.map((w) => el("span", { class: "who-chip" }, el("span", { "aria-hidden": "true" }, PEOPLE[w].icon), PEOPLE[w].label))),
        cite ? el("p", { class: "cite" },
          el("strong", {}, `WCAG ${cite.sc} ${cite.handle} (Level ${cite.level})`), ": ", cite.why_important || cite.goal, " ",
          el("a", { href: cite.understanding_url, target: "_blank", rel: "noopener" }, "What W3C says",
            el("span", { class: "visually-hidden" }, ` about ${cite.sc} ${cite.handle} (opens in a new tab)`))) :
          el("p", { class: "cite muted" }, "Best practice (not a WCAG requirement on its own). ", f.help_url ? el("a", { href: f.help_url, target: "_blank", rel: "noopener" }, "Learn more",
            el("span", { class: "visually-hidden" }, ` about “${d.title}” (opens in a new tab)`)) : null),
        el("details", { class: "elements" }, el("summary", {}, `Where it happens (${f.nodes.length})`), elements)));
  }

  const FILTERS = [["all", "All"], ["auto-verified", "Confirmed"], ["ai-high-confidence", "Found by AI"], ["needs-review", "Needs a human"]];
  const filters = el("div", { class: "filters", role: "group", "aria-label": "Show problems" },
    FILTERS.map(([key, label]) => {
      const n = key === "all" ? groups.length : groups.filter((g) => g.f.confidence === key).length;
      return el("button", { type: "button", "aria-pressed": String(key === "all"), onclick: (e) => {
        filters.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
        list.querySelectorAll(".finding").forEach((c) => { c.hidden = key !== "all" && c.dataset.conf !== key; });
        live.textContent = `Showing ${n} ${label.toLowerCase()} problem types.`;
      } }, `${label} (${n})`);
    }));
  const live = el("p", { class: "visually-hidden", "aria-live": "polite" });
  groups.forEach((g) => list.append(findingCard(g)));

  const resolved = report.resolved || [];
  const extras = el("div", {},
    resolved.length ? el("details", { class: "finding", style: "padding:16px 20px" },
      el("summary", { style: "font-weight:650;cursor:pointer" }, `Settled as passing (${resolved.length})`),
      el("p", { class: "muted", style: "margin-top:10px" }, "Rule checkers couldn't decide these (usually text over a photo or gradient). Parity measured the real pixels and they pass:"),
      resolved.map((r) => el("div", { class: "el" }, el("code", {}, r.target), el("p", { class: "evidence" }, r.evidence)))) : null,
    (report.notes || []).length ? el("div", { class: "finding", style: "padding:16px 20px" },
      el("h3", { style: "font:650 1rem var(--sans)" }, "Notes from this scan"),
      el("ul", {}, report.notes.map((n) => el("li", {}, n)))) : null);

  const body = el("div", { class: "wrap report-body" },
    el("div", { class: "shot-panel" }, tabs, frame, note),
    el("div", {}, el("h2", {}, "What to fix, most important first"), filters, live, list, extras));
  app.replaceChildren(head, body);
}

function checkNames(report) {
  const names = { "contrast-meter": "contrast measured from pixels", "parity-rules": "alt-text rules", "interaction-agent": "keyboard walk" };
  const out = [`accessibility rules (${report.engine.replace("axe v", "axe-core ")})`];
  for (const a of report.agents || []) {
    if (a.startsWith("vision-agent")) out.push(`image checks by AI (${a.split(":")[1] || "Gemini"})`);
    else out.push(names[a] || a);
  }
  return out;
}

function kpi(v, l) { return el("div", { class: "kpi" }, el("div", { class: "v" }, String(v)), el("div", { class: "l" }, l)); }

function download(report) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: "parity-report.json" });
  document.body.append(a); a.click(); a.remove();
}

/* ---------------------------------------------------------------- start */

(async () => {
  try {
    let report = null;
    if (params.get("scan")) report = await pollScan(params.get("scan"));
    else report = await loadExample(params.get("example") || "mars");
    if (params.get("example")) document.getElementById("nav-report").setAttribute("aria-current", "page");
    if (report) render(report);
  } catch (e) {
    setStatus([el("h1", {}, "We couldn't load this report"), el("p", {}, e.message)]);
  }
})();
