import { api, el, mountChat, setGithubLinks, wireSpeakButtons } from "./site.js";
import { CONFIDENCE, describe, IMPACT } from "./explain.js";

setGithubLinks();
wireSpeakButtons();
mountChat();

/* ---------------------------------------------------------------- scan form */
const form = document.getElementById("scan-form");
const input = document.getElementById("scan-url");
const errorBox = document.getElementById("scan-error");
const button = document.getElementById("scan-btn");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.textContent = "";
  let url = input.value.trim();
  if (!url) { errorBox.textContent = "Enter the address of a web page, e.g. https://example.com"; input.focus(); return; }
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;
  button.disabled = true;
  button.textContent = "Starting scan…";
  try {
    const job = await api("/api/scans", { method: "POST", body: JSON.stringify({ url }) },
      () => { button.textContent = "Waking up the server…"; });
    window.location.href = `report.html?scan=${encodeURIComponent(job.id)}`;
  } catch (err) {
    errorBox.textContent = err.message;
    button.disabled = false;
    button.textContent = "Scan this page";
    input.focus();
  }
});

/* ---------------------------------------------------------------- low-vision toggle */
document.getElementById("lowvision-toggle").addEventListener("change", (e) => {
  document.getElementById("contrast-demo").classList.toggle("lowvision", e.target.checked);
});

/* ---------------------------------------------------------------- keyboard demo */
const items = [...document.querySelectorAll("#kbd-row .kbd-item")];
const status = document.getElementById("kbd-status");
let pos = -1;
document.getElementById("tab-key").addEventListener("click", () => {
  items.forEach((i) => i.classList.remove("is-focused"));
  pos = (pos + 1) % items.length;
  if (items[pos].hasAttribute("data-skip")) {
    items[pos].classList.add("is-skipped");
    const skipped = items[pos].textContent;
    pos = (pos + 1) % items.length;
    items[pos].classList.add("is-focused");
    status.textContent = `Focus jumped to “${items[pos].textContent}”. “${skipped}” was skipped: it's a clickable box, not a real link, so the keyboard can't reach it.`;
    return;
  }
  items[pos].classList.add("is-focused");
  status.textContent = `Focus is on “${items[pos].textContent}”.`;
});

/* ---------------------------------------------------------------- real report preview */
(async () => {
  try {
    const report = await (await fetch("examples/mars/report.json")).json();
    const confirmed = report.findings.filter((f) => f.confidence !== "needs-review");
    const elements = confirmed.reduce((n, f) => n + f.nodes.length, 0);
    const review = report.findings.filter((f) => f.confidence === "needs-review").reduce((n, f) => n + f.nodes.length, 0);
    const kpi = (v, l) => el("div", { class: "kpi" }, el("div", { class: "v" }, String(v)), el("div", { class: "l" }, l));
    document.getElementById("kpis").append(
      kpi(confirmed.length, "kinds of problems found"),
      kpi(elements, "places on the page affected"),
      kpi((report.resolved || []).length, "unclear cases settled by measuring"),
      kpi(review, "places left for a quick human check"),
    );
    // "Biggest" = how much of the page it affects, weighted by severity; same problem found by
    // rules and by AI counts once; best-practice-only items (no WCAG rule) are left out.
    const weight = { critical: 3, serious: 2, moderate: 1, minor: 0.5 };
    const byRule = new Map();
    for (const f of confirmed.filter((f) => (f.wcag_criteria || []).length)) {
      const g = byRule.get(f.rule_id) || { f, n: 0, conf: new Set() };
      g.n += f.nodes.length; g.conf.add(f.confidence); byRule.set(f.rule_id, g);
    }
    const top = [...byRule.values()].sort((a, b) => b.n * (weight[b.f.impact] || 1) - a.n * (weight[a.f.impact] || 1)).slice(0, 4);
    const list = document.getElementById("top-issues");
    top.forEach(({ f, n, conf }) => {
      const d = describe(f);
      const how = [...conf].map((c) => CONFIDENCE[c]?.label).join(" + ");
      list.append(el("li", {}, el("span", { class: "n" }, `×${n}`),
        el("div", {}, el("strong", {}, d.title), el("br"), el("span", { class: "muted" }, `${IMPACT[f.impact]?.label || ""} · ${how} · WCAG ${f.wcag_criteria.join(", ")}`))));
    });
  } catch (e) {
    document.getElementById("kpis").textContent = "The example report couldn't be loaded.";
  }
})();
