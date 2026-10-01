// Talks to the FastAPI backend, streams progress, shows the article, remembers drafts.
const API = "http://localhost:8000";

const $ = (id) => document.getElementById(id);
const els = {
  topic: $("topic"),
  generate: $("generate"),
  progress: $("progress"),
  drafts: $("drafts"),
  homeView: $("home-view"),
  articleView: $("article-view"),
  back: $("back"),
  articleTitle: $("article-title"),
  articleBody: $("article-body"),
};

// Strip stray Markdown symbols (**, #) so titles display cleanly.
const cleanTitle = (t) => (t || "Untitled").replace(/[*#`]/g, "").trim();

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
  els.articleView.classList.add("hidden");
  els.homeView.classList.remove("hidden");
}
function showArticle(title, content) {
  els.articleTitle.textContent = cleanTitle(title);
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
    card.addEventListener("click", () => showArticle(d.title, d.content));
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

  try {
    const resp = await fetch(API + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
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
      topic,
      date: new Date().toLocaleString(),
    };
    saveDraft(draft);
    els.progress.classList.add("hidden");
    showArticle(draft.title, draft.content);
  }
}

els.generate.addEventListener("click", generate);
els.topic.addEventListener("keydown", (e) => {
  if (e.key === "Enter") generate();
});

// on load
renderDrafts();