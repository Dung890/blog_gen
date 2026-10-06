// Talks to the FastAPI backend, streams progress, shows the article, remembers drafts.
const API = "http://localhost:8000";

const $ = (id) => document.getElementById(id);
const els = {
  topic: $("topic"),
  generate: $("generate"),
  tone: $("tone"),
  length: $("length"),
  audience: $("audience"),
  progress: $("progress"),
  drafts: $("drafts"),
  homeView: $("home-view"),
  articleView: $("article-view"),
  back: $("back"),
  articleTitle: $("article-title"),
  articleMeta: $("article-meta"),
  articleBody: $("article-body"),
  copyMd: $("copy-md"),
  dlMd: $("dl-md"),
  dlHtml: $("dl-html"),
  dlDocx: $("dl-docx"),
};

// The currently-open article (for export).
let currentContent = "";
let currentTitle = "";

// Strip stray Markdown symbols (**, #) so titles display cleanly.
const cleanTitle = (t) => (t || "Untitled").replace(/[*#`]/g, "").trim();

// ---- reader analytics: measure engaged time silently (no UI) ----
let readSeconds = 0;
let readTimer = null;
let currentSlug = null;

function tickOn() {
  if (!readTimer) readTimer = setInterval(() => readSeconds++, 1000);
}
function tickOff() {
  clearInterval(readTimer);
  readTimer = null;
}
function flushReading() {
  if (currentSlug && readSeconds > 0) {
    try {
      fetch(API + "/analytics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: currentSlug, seconds: readSeconds }),
        keepalive: true, // lets it complete even if the page is closing
      });
    } catch {}
  }
  readSeconds = 0;
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) tickOff();
  else if (!els.articleView.classList.contains("hidden")) tickOn();
});
window.addEventListener("pagehide", flushReading);

let mode = "fast";

// ---- mode toggle ----
document.querySelectorAll(".seg").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".seg").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    mode = btn.dataset.mode;
  });
});

// ---- switching between the home view and the article view ----
function showHome() {
  flushReading();
  tickOff();
  els.articleView.classList.add("hidden");
  els.homeView.classList.remove("hidden");
}
function renderMeta(seo) {
  if (!seo) return "";
  const time = seo.reading_time_min ? `<span class="read-time">${seo.reading_time_min} min read</span>` : "";
  const tags = (seo.tags || []).map((t) => `<span class="tag">${t}</span>`).join("");
  const desc = seo.meta_description ? `<p class="meta-desc">${seo.meta_description}</p>` : "";
  return `<div class="meta-row">${time}${tags}</div>${desc}`;
}

async function showActualReadTime(slug) {
  if (!slug) return;
  try {
    const r = await fetch(`${API}/analytics/${encodeURIComponent(slug)}`);
    const s = await r.json();
    if (s.count > 0 && s.average_seconds) {
      const m = Math.floor(s.average_seconds / 60);
      const sec = Math.round(s.average_seconds % 60);
      const row = els.articleMeta.querySelector(".meta-row");
      if (row) {
        const span = document.createElement("span");
        span.className = "actual-time";
        span.textContent = `· avg ${m}m ${sec}s actual (${s.count} ${s.count === 1 ? "read" : "reads"})`;
        row.appendChild(span);
      }
    }
  } catch {}
}

function showArticle(title, content, seo) {
  flushReading(); // save any time from a previously open article
  currentSlug = (seo && seo.slug) || null;
  tickOff();
  if (!document.hidden) tickOn();
  currentContent = content || "";
  currentTitle = cleanTitle(title);
  els.articleTitle.textContent = currentTitle;
  els.articleMeta.innerHTML = renderMeta(seo);
  showActualReadTime(currentSlug); // append real avg read time if data exists
  els.articleBody.innerHTML = window.marked.parse(content || "");
  els.homeView.classList.add("hidden");
  els.articleView.classList.remove("hidden");
  window.scrollTo(0, 0);
}
els.back.addEventListener("click", showHome);

// ---- recent drafts, saved in the browser (localStorage) ----
function loadDrafts() {
  try {
    return JSON.parse(localStorage.getItem("drafts") || "[]");
  } catch {
    return [];
  }
}
function saveDraft(draft) {
  const drafts = loadDrafts();
  drafts.unshift(draft); // newest first
  try {
    localStorage.setItem("drafts", JSON.stringify(drafts.slice(0, 6)));
  } catch {}
  renderDrafts();
}
function renderDrafts() {
  const drafts = loadDrafts();
  if (!drafts.length) {
    els.drafts.innerHTML = '<p class="empty">Your generated blogs will appear here.</p>';
    return;
  }
  els.drafts.innerHTML = "";
  drafts.forEach((d) => {
    const card = document.createElement("div");
    card.className = "draft-card";
    card.innerHTML = `<h3>${d.title}</h3><div class="meta">${d.date}</div>`;
    card.addEventListener("click", () => showArticle(d.title, d.content, d.seo));
    els.drafts.appendChild(card);
  });
}

// ---- generation with live streaming ----
async function generate() {
  const topic = els.topic.value.trim();
  if (!topic) {
    els.topic.focus();
    return;
  }
  const endpoint = mode === "deep" ? "/blogs/deep" : "/blogs/stream";

  els.generate.disabled = true;
  els.progress.classList.remove("hidden");
  els.progress.innerHTML = '<div class="row">Starting…</div>';
  let blog = {};
  let seo = null;

  const payload = {
    topic,
    tone: els.tone.value,
    length: els.length.value,
    audience: els.audience.value,
  };

  try {
    const resp = await fetch(API + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5).trim());
        if (ev.event === "step") {
          els.progress.innerHTML += `<div class="row"><span class="tick">✓</span> ${ev.message}</div>`;
        } else if (ev.event === "done") {
          blog = ev.blog || {};
          seo = ev.seo || null;
        } else if (ev.event === "error") {
          els.progress.innerHTML += `<div class="row">⚠ ${ev.message}</div>`;
        }
      }
    }
  } catch (err) {
    const msg = err.message.includes("fetch") ? "Backend not reachable on :8000" : err.message;
    els.progress.innerHTML += `<div class="row">⚠ ${msg}</div>`;
  } finally {
    els.generate.disabled = false;
  }

  if (blog.content) {
    const draft = {
      title: cleanTitle(blog.title || topic),
      content: blog.content,
      seo,
      topic,
      date: new Date().toLocaleString(),
    };
    saveDraft(draft);
    els.progress.classList.add("hidden");
    showArticle(draft.title, draft.content, draft.seo);
  }
}

els.generate.addEventListener("click", generate);
els.topic.addEventListener("keydown", (e) => {
  if (e.key === "Enter") generate();
});

// ---- export helpers ----
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
function fileBase() {
  return (currentSlug || currentTitle || "blog").toString().slice(0, 60);
}

els.copyMd.addEventListener("click", async () => {
  await navigator.clipboard.writeText(currentContent);
  els.copyMd.textContent = "Copied!";
  setTimeout(() => (els.copyMd.textContent = "Copy"), 1500);
});

els.dlMd.addEventListener("click", () => {
  downloadBlob(new Blob([currentContent], { type: "text/markdown" }), fileBase() + ".md");
});

els.dlHtml.addEventListener("click", () => {
  const body = window.marked.parse(currentContent || "");
  const html =
    `<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">` +
    `<title>${currentTitle}</title></head><body>\n${body}\n</body></html>`;
  downloadBlob(new Blob([html], { type: "text/html" }), fileBase() + ".html");
});

els.dlDocx.addEventListener("click", async () => {
  els.dlDocx.textContent = "…";
  try {
    const r = await fetch(API + "/export/docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: currentTitle, content: currentContent }),
    });
    downloadBlob(await r.blob(), fileBase() + ".docx");
  } catch {
    alert("Could not export .docx (is the backend running?)");
  } finally {
    els.dlDocx.textContent = "Download .docx";
  }
});

// on load
renderDrafts();