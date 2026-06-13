/* 墨涧工坊 — 前端核心逻辑 */
"use strict";

// ── 全局状态 ──────────────────────────────────────────────────────────────────
let history = [];          // 当前对话消息数组 {role, content}
let isGenerating = false;
let abortController = null;
let activeConvId = null;   // 当前对话 ID

// ── DOM 引用 ──────────────────────────────────────────────────────────────────
const messagesEl   = document.getElementById("messages");
const welcomeEl    = document.getElementById("welcome");
const inputEl      = document.getElementById("input");
const sendBtn      = document.getElementById("sendBtn");
const stopBtn      = document.getElementById("stopBtn");
const thinkingTog  = document.getElementById("thinkingToggle");
const maxTokensEl  = document.getElementById("maxTokens");
const maxTokensVal = document.getElementById("maxTokensValue");
const statusDot    = document.getElementById("statusDot");
const statusLabel  = document.getElementById("statusLabel");
const statusDetail = document.getElementById("statusDetail");
const modelBadge   = document.getElementById("modelBadge");
const errorToast   = document.getElementById("errorToast");
const convListEl   = document.getElementById("convList");
const newConvBtn   = document.getElementById("newConvBtn");
const chatTitle    = document.getElementById("chatTitle");
const hamburgerBtn = document.getElementById("hamburgerBtn");
const sidebar      = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebarOverlay");

// ── 用户区 DOM ────────────────────────────────────────────────────────────────
const authSection   = document.getElementById("authSection");
const userSection   = document.getElementById("userSection");
const usernameInput = document.getElementById("usernameInput");
const registerBtn   = document.getElementById("registerBtn");
const loginBtn      = document.getElementById("loginBtn");
const currentUser   = document.getElementById("currentUser");
const logoutBtn     = document.getElementById("logoutBtn");

// ── 工具函数 ──────────────────────────────────────────────────────────────────
function getGuestId() {
  let id = localStorage.getItem("guest_id");
  if (!id) { id = crypto.randomUUID(); localStorage.setItem("guest_id", id); }
  return id;
}

function getAuthToken() { return localStorage.getItem("auth_token"); }
function setAuthToken(t) { localStorage.setItem("auth_token", t); }
function clearAuthToken() { localStorage.removeItem("auth_token"); }

function apiHeaders() {
  const h = { "Content-Type": "application/json" };
  const tok = getAuthToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  else h["X-Guest-Id"] = getGuestId();
  return h;
}

function showError(msg) {
  errorToast.textContent = msg;
  errorToast.classList.add("show");
  setTimeout(() => errorToast.classList.remove("show"), 3500);
}

function showToast(msg) {
  errorToast.textContent = msg;
  errorToast.style.background = "rgba(74,107,93,0.9)";
  errorToast.classList.add("show");
  setTimeout(() => { errorToast.classList.remove("show"); errorToast.style.background = ""; }, 2500);
}

function formatTime(isoStr) {
  const d = isoStr ? new Date(isoStr + "Z") : new Date();
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

marked.setOptions({ breaks: true, gfm: true });
function renderMarkdown(text) {
  if (!text) return "";
  return DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
}

// ── HTML 代码块预览 ────────────────────────────────────────────────────────────
const htmlPreviewModal   = document.getElementById("htmlPreviewModal");
const htmlPreviewFrame   = document.getElementById("htmlPreviewFrame");
const htmlPreviewBackdrop = document.getElementById("htmlPreviewBackdrop");
const htmlPreviewClose   = document.getElementById("htmlPreviewClose");

function isHtmlCodeBlock(codeEl) {
  const cls = [...codeEl.classList].find(c => c.startsWith("language-"));
  const lang = cls ? cls.slice(9).toLowerCase() : "";
  if (lang === "html" || lang === "htm") return true;
  const t = codeEl.textContent.trim();
  return /^<!DOCTYPE\s+html/i.test(t) || /^<html[\s>]/i.test(t);
}

function openHtmlPreview(html) {
  htmlPreviewFrame.srcdoc = html;
  htmlPreviewModal.classList.add("open");
  htmlPreviewModal.setAttribute("aria-hidden","false");
}
function closeHtmlPreview() {
  htmlPreviewModal.classList.remove("open");
  htmlPreviewModal.setAttribute("aria-hidden","true");
  htmlPreviewFrame.srcdoc = "";
}

function enhanceHtmlCodeBlocks(root) {
  root.querySelectorAll("pre code").forEach(codeEl => {
    if (!isHtmlCodeBlock(codeEl)) return;
    const pre = codeEl.parentElement;
    if (!pre || pre.dataset.previewEnhanced) return;
    pre.dataset.previewEnhanced = "1";
    const wrap = document.createElement("div"); wrap.className = "code-block-wrap";
    const tb = document.createElement("div"); tb.className = "code-block-toolbar";
    tb.innerHTML = `<span class="code-block-lang">HTML</span>
      <div class="code-block-actions">
        <button type="button" class="btn-code-action primary" data-action="preview">预览</button>
        <button type="button" class="btn-code-action" data-action="newtab">新标签</button>
      </div>`;
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(tb); wrap.appendChild(pre);
    tb.querySelector('[data-action="preview"]').addEventListener("click", () => openHtmlPreview(codeEl.textContent));
    tb.querySelector('[data-action="newtab"]').addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob([codeEl.textContent], {type:"text/html;charset=utf-8"}));
      window.open(url,"_blank","noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    });
  });
}

htmlPreviewClose.addEventListener("click", closeHtmlPreview);
htmlPreviewBackdrop.addEventListener("click", closeHtmlPreview);
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && htmlPreviewModal.classList.contains("open")) closeHtmlPreview();
});

// ── 健康检查 ──────────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const res = await fetch("/health");
    const data = await res.json();
    statusDot.className = "status-dot online";
    statusLabel.textContent = "服务在线";
    const modelName = data.model?.split(/[\\/]/).pop() || "Qwen3.5-0.8B";
    const accessUrl = data.urls?.lan || window.location.origin + "/";
    statusDetail.innerHTML = `${modelName} · ${data.device?.toUpperCase()||"CPU"}<br><a href="${accessUrl}" style="color:var(--jade-soft)">${accessUrl}</a>`;
    modelBadge.textContent = `${modelName} · ${data.device?.toUpperCase()||"CPU"}`;
    return true;
  } catch {
    statusDot.className = "status-dot offline";
    statusLabel.textContent = "服务离线";
    statusDetail.textContent = "请先运行 python serve.py";
    return false;
  }
}

// ── 思考块解析 ────────────────────────────────────────────────────────────────
function stripThinkOpen(text) {
  return text.replace(/^<(?:think|redacted_thinking)>\s*/i,"").trimStart();
}
function parseReply(text) {
  const thinkEnd = /<\/think>|<\/redacted_thinking>/i;
  if (thinkEnd.test(text)) {
    const idx = text.search(thinkEnd);
    const endLen = text.match(thinkEnd)[0].length;
    const thinking = stripThinkOpen(text.slice(0, idx)).trim();
    const answer = text.slice(idx + endLen).trim();
    return { thinking: thinking || null, answer: answer || text };
  }
  return { thinking: null, answer: text };
}

// ── 消息操作栏 ────────────────────────────────────────────────────────────────
function createActionBar(role) {
  const bar = document.createElement("div");
  bar.className = "msg-actions";
  if (role === "user") {
    bar.innerHTML = `
      <button class="msg-action-btn" data-action="copy" title="复制">
        <svg viewBox="0 0 24 24"><path d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/></svg>
      </button>
      <button class="msg-action-btn" data-action="edit" title="编辑">
        <svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
      </button>`;
  } else {
    bar.innerHTML = `
      <button class="msg-action-btn" data-action="copy" title="复制">
        <svg viewBox="0 0 24 24"><path d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/></svg>
      </button>
      <button class="msg-action-btn" data-action="regen" title="重新生成">
        <svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
      </button>
      <button class="msg-action-btn" data-action="share" title="分享">
        <svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92 0-1.61-1.31-2.92-2.92-2.92z"/></svg>
      </button>`;
  }
  return bar;
}

// ── 消息渲染 ──────────────────────────────────────────────────────────────────
const WELCOME_HTML = welcomeEl ? welcomeEl.innerHTML : "";

function setAnswerContent(el, text, { streaming = false } = {}) {
  el.className = streaming ? "stream-text" : "md-body";
  if (streaming) { el.textContent = text; return; }
  el.innerHTML = renderMarkdown(text);
  enhanceHtmlCodeBlocks(el);
}

function createMessage(role, content, { thinking = null, msgId = null, timestamp = null, interrupted = false } = {}) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (msgId) div.dataset.messageId = msgId;
  div.dataset.role = role;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = role === "user" ? "你" : "涧";

  const body = document.createElement("div");
  body.className = "msg-body";

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = role === "user"
    ? `你 · ${formatTime(timestamp)}`
    : `墨涧 · ${formatTime(timestamp)}`;

  const contentEl = document.createElement("div");
  contentEl.className = "msg-content";

  if (thinking) {
    const tb = document.createElement("div"); tb.className = "thinking-block";
    tb.innerHTML = `<div class="thinking-label">思考过程</div>${escapeHtml(thinking)}`;
    contentEl.appendChild(tb);
  }

  const answerEl = document.createElement(role === "assistant" ? "div" : "span");
  if (role === "assistant") {
    const { answer } = parseReply(content);
    setAnswerContent(answerEl, answer || content);
  } else {
    answerEl.textContent = content;
  }
  contentEl.appendChild(answerEl);

  if (interrupted) {
    const badge = document.createElement("span");
    badge.className = "interrupted-badge";
    badge.textContent = "（已中断）";
    contentEl.appendChild(badge);
  }

  body.appendChild(meta);
  body.appendChild(contentEl);
  body.appendChild(createActionBar(role));
  div.appendChild(avatar);
  div.appendChild(body);
  return div;
}

function createStreamingMessage() {
  const div = document.createElement("div");
  div.className = "msg assistant streaming";
  div.dataset.role = "assistant";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = "涧";

  const body = document.createElement("div");
  body.className = "msg-body";

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = `墨涧 · 生成中`;

  const contentEl = document.createElement("div");
  contentEl.className = "msg-content";

  const answerEl = document.createElement("span");
  answerEl.className = "stream-text";
  contentEl.appendChild(answerEl);

  body.appendChild(meta);
  body.appendChild(contentEl);
  div.appendChild(avatar);
  div.appendChild(body);
  messagesEl.appendChild(div);
  scrollToBottom();
  return { el: div, contentEl, answerEl };
}

function finalizeStreamingMessage(wrapper, fullText, { msgId = null, interrupted = false } = {}) {
  const { thinking, answer } = parseReply(fullText);
  wrapper.el.classList.remove("streaming");
  if (msgId) wrapper.el.dataset.messageId = msgId;
  wrapper.el.querySelector(".msg-meta").textContent = `墨涧 · ${formatTime(null)}`;
  wrapper.contentEl.innerHTML = "";

  if (thinking) {
    const tb = document.createElement("div"); tb.className = "thinking-block";
    tb.innerHTML = `<div class="thinking-label">思考过程</div>${escapeHtml(thinking)}`;
    wrapper.contentEl.appendChild(tb);
  }

  const answerEl = document.createElement("div");
  setAnswerContent(answerEl, answer || fullText);
  wrapper.contentEl.appendChild(answerEl);

  if (interrupted) {
    const badge = document.createElement("span");
    badge.className = "interrupted-badge";
    badge.textContent = "（已中断）";
    wrapper.contentEl.appendChild(badge);
  }

  wrapper.el.querySelector(".msg-body").appendChild(createActionBar("assistant"));
}

function showTyping() {
  const div = document.createElement("div");
  div.className = "msg assistant"; div.id = "typing";
  div.innerHTML = `<div class="msg-avatar">涧</div>
    <div class="msg-body">
      <div class="msg-meta">墨涧 · 生成中</div>
      <div class="msg-content"><div class="typing-indicator"><span></span><span></span><span></span></div></div>
    </div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
}
function hideTyping() { document.getElementById("typing")?.remove(); }
function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

// ── SSE 流读取 ────────────────────────────────────────────────────────────────
async function consumeStream(response, onChunk) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (payload === "[DONE]") return;
      const data = JSON.parse(payload);
      if (data.text) onChunk(data.text);
    }
  }
}

// ── 发送消息（主流程）─────────────────────────────────────────────────────────
async function sendMessage(text, { editMsgId = null, editSortOrder = null } = {}) {
  const prompt = text.trim();
  if (!prompt || isGenerating) return;

  const online = await checkHealth();
  if (!online) { showError("模型服务未启动，请先运行 serve.py"); return; }

  // 确保有当前对话
  if (!activeConvId) {
    const conv = await createConversation();
    if (!conv) return;
  }

  // 编辑模式：更新消息内容并截断后续
  if (editMsgId && editSortOrder !== null) {
    await fetch(`/api/conversations/${activeConvId}/messages/${editMsgId}`, {
      method: "PATCH", headers: apiHeaders(),
      body: JSON.stringify({ content: prompt }),
    });
    await fetch(`/api/conversations/${activeConvId}/messages/from/${editMsgId}`, {
      method: "DELETE", headers: apiHeaders(),
    });
    // 等幂：重新 append user 消息
  }

  // 移除欢迎页
  document.getElementById("welcome")?.remove();

  // 保存 user 消息到 DB
  const userMsgRes = await fetch(`/api/conversations/${activeConvId}/messages`, {
    method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ role: "user", content: prompt }),
  });
  const userMsg = await userMsgRes.json();

  history.push({ role: "user", content: prompt });
  const userEl = createMessage("user", prompt, { msgId: userMsg.id });
  messagesEl.appendChild(userEl);
  scrollToBottom();

  inputEl.value = ""; inputEl.style.height = "auto";
  setGenerating(true);

  const streamMsg = createStreamingMessage();
  let fullText = "";
  let interrupted = false;

  abortController = new AbortController();

  try {
    const res = await fetch("/chat/stream", {
      method: "POST",
      headers: apiHeaders(),
      signal: abortController.signal,
      body: JSON.stringify({
        messages: history,
        enable_thinking: thinkingTog.checked,
        max_new_tokens: parseInt(maxTokensEl.value, 10),
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `请求失败 (${res.status})`);
    }

    await consumeStream(res, chunk => {
      fullText += chunk;
      streamMsg.answerEl.textContent = fullText;
      scrollToBottom();
    });
  } catch (err) {
    if (err.name === "AbortError") {
      interrupted = true;
    } else {
      streamMsg.el.remove();
      history.pop();
      showError(err.message || "生成失败，请重试");
      setGenerating(false);
      return;
    }
  }

  // 保存 assistant 消息（中断时有内容也保存）
  let asstMsgId = null;
  if (fullText) {
    const asstMsgRes = await fetch(`/api/conversations/${activeConvId}/messages`, {
      method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ role: "assistant", content: fullText + (interrupted ? "\n（已中断）" : "") }),
    });
    const asstMsg = await asstMsgRes.json();
    asstMsgId = asstMsg.id;
    history.push({ role: "assistant", content: fullText });
  } else if (interrupted) {
    streamMsg.el.remove();
    setGenerating(false);
    await refreshConvList();
    return;
  }

  finalizeStreamingMessage(streamMsg, fullText, { msgId: asstMsgId, interrupted });
  scrollToBottom();
  setGenerating(false);
  await refreshConvList();
}

// ── 生成状态控制 ──────────────────────────────────────────────────────────────
function setGenerating(v) {
  isGenerating = v;
  sendBtn.style.display = v ? "none" : "flex";
  stopBtn.style.display = v ? "flex" : "none";
  inputEl.disabled = v;
  if (!v) { abortController = null; inputEl.focus(); }
}

stopBtn.addEventListener("click", () => {
  if (abortController) abortController.abort();
});

// ── 消息操作事件委托 ──────────────────────────────────────────────────────────
messagesEl.addEventListener("click", async e => {
  const btn = e.target.closest(".msg-action-btn");
  if (!btn || isGenerating) return;
  const action = btn.dataset.action;
  const msgEl = btn.closest(".msg");
  if (!msgEl) return;
  const msgId = msgEl.dataset.messageId;
  const role = msgEl.dataset.role;

  if (action === "copy") {
    let text = "";
    if (role === "user") {
      text = msgEl.querySelector("span")?.textContent || "";
    } else {
      const mdBody = msgEl.querySelector(".md-body");
      text = mdBody ? mdBody.innerText : (msgEl.querySelector(".msg-content")?.innerText || "");
    }
    await navigator.clipboard.writeText(text).catch(() => {});
    showToast("已复制到剪贴板");
  }

  if (action === "edit" && role === "user") {
    const span = msgEl.querySelector("span");
    const originalText = span?.textContent || "";
    // 找到该消息在 history 中的 sort_order（通过 DOM 顺序推断）
    inputEl.value = originalText;
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
    inputEl.focus();
    inputEl.dataset.editMsgId = msgId || "";

    // 记录 sort_order：从 DOM 中所有用户消息位置推断
    const allMsgs = [...messagesEl.querySelectorAll(".msg[data-message-id]")];
    const idx = allMsgs.findIndex(m => m.dataset.messageId === msgId);
    inputEl.dataset.editSortOrder = idx; // 仅作参考，实际截断用 msg_id
  }

  if (action === "regen" && role === "assistant") {
    if (!activeConvId || !msgId) return;
    // 截断从该 assistant 消息起
    await fetch(`/api/conversations/${activeConvId}/messages/from/${msgId}`, {
      method: "DELETE", headers: apiHeaders(),
    });
    // 从 DOM 删除该消息及之后所有消息
    const allMsgs = [...messagesEl.querySelectorAll(".msg")];
    const idx = allMsgs.indexOf(msgEl);
    allMsgs.slice(idx).forEach(m => m.remove());
    // 重新 history 截断到上一条 user 消息
    const lastUserIdx = [...history].reverse().findIndex(m => m.role === "user");
    if (lastUserIdx === -1) return;
    const userHistIdx = history.length - 1 - lastUserIdx;
    const lastUserMsg = history[userHistIdx].content;
    history = history.slice(0, userHistIdx);
    sendMessage(lastUserMsg);
  }

  if (action === "share" && role === "assistant") {
    if (!activeConvId || !msgId) { showError("请先保存对话"); return; }
    try {
      const res = await fetch(`/api/conversations/${activeConvId}/messages/${msgId}/share`, {
        method: "POST", headers: apiHeaders(),
      });
      const data = await res.json();
      await navigator.clipboard.writeText(data.url).catch(() => {});
      showToast("分享链接已复制到剪贴板");
    } catch {
      showError("生成分享链接失败");
    }
  }
});

// 编辑提交：读取 dataset
sendBtn.addEventListener("click", () => {
  const editMsgId = inputEl.dataset.editMsgId || null;
  const editSortOrder = inputEl.dataset.editSortOrder ? parseInt(inputEl.dataset.editSortOrder) : null;
  delete inputEl.dataset.editMsgId;
  delete inputEl.dataset.editSortOrder;
  sendMessage(inputEl.value, { editMsgId, editSortOrder });
});

inputEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});

maxTokensEl.addEventListener("input", () => {
  maxTokensVal.textContent = `${maxTokensEl.value} tokens`;
});

// ── 对话管理 ──────────────────────────────────────────────────────────────────
async function createConversation() {
  try {
    const res = await fetch("/api/conversations", { method: "POST", headers: apiHeaders() });
    const conv = await res.json();
    activeConvId = conv.id;
    chatTitle.textContent = conv.title;
    history = [];
    return conv;
  } catch {
    showError("创建对话失败"); return null;
  }
}

async function loadConversation(convId) {
  try {
    const res = await fetch(`/api/conversations/${convId}`, { headers: apiHeaders() });
    const conv = await res.json();
    activeConvId = conv.id;
    chatTitle.textContent = conv.title;
    history = conv.messages.map(m => ({ role: m.role, content: m.content }));
    renderMessages(conv.messages);
    highlightActiveConv();
  } catch {
    showError("加载对话失败");
  }
}

function renderMessages(msgs) {
  messagesEl.innerHTML = "";
  if (!msgs.length) {
    messagesEl.innerHTML = `<div class="welcome" id="welcome">${WELCOME_HTML}</div>`;
    bindSuggestions();
    return;
  }
  for (const m of msgs) {
    const interrupted = m.content.endsWith("（已中断）");
    const content = interrupted ? m.content.replace(/\n?（已中断）$/, "") : m.content;
    const el = createMessage(m.role, content, {
      msgId: m.id,
      timestamp: m.created_at,
      interrupted,
    });
    messagesEl.appendChild(el);
  }
  scrollToBottom();
}

async function refreshConvList() {
  try {
    const res = await fetch("/api/conversations", { headers: apiHeaders() });
    const data = await res.json();
    renderConvList(data.groups || {});
  } catch { /* ignore */ }
}

function renderConvList(groups) {
  convListEl.innerHTML = "";
  const order = ["今天","昨天","过去 7 天","更早"];
  const allKeys = [...new Set([...order, ...Object.keys(groups)])];
  for (const key of allKeys) {
    const convs = groups[key];
    if (!convs || !convs.length) continue;
    const label = document.createElement("div");
    label.className = "conv-group-label";
    label.textContent = key;
    convListEl.appendChild(label);
    for (const conv of convs) {
      convListEl.appendChild(makeConvItem(conv));
    }
  }
  highlightActiveConv();
}

function makeConvItem(conv) {
  const item = document.createElement("div");
  item.className = "conv-item";
  item.dataset.convId = conv.id;

  const titleEl = document.createElement("span");
  titleEl.className = "conv-item-title";
  titleEl.textContent = conv.title;

  const editBtn = document.createElement("button");
  editBtn.className = "conv-item-action";
  editBtn.title = "重命名";
  editBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;

  const delBtn = document.createElement("button");
  delBtn.className = "conv-item-action conv-item-del";
  delBtn.title = "删除";
  delBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`;

  item.appendChild(titleEl);
  item.appendChild(editBtn);
  item.appendChild(delBtn);

  item.addEventListener("click", e => {
    if (e.target.closest(".conv-item-action")) return;
    loadConversation(conv.id);
    closeSidebar();
  });

  editBtn.addEventListener("click", async e => {
    e.stopPropagation();
    const newTitle = prompt("输入新对话名称：", conv.title);
    if (!newTitle || !newTitle.trim()) return;
    await fetch(`/api/conversations/${conv.id}`, {
      method: "PATCH", headers: apiHeaders(),
      body: JSON.stringify({ title: newTitle.trim() }),
    });
    if (conv.id === activeConvId) chatTitle.textContent = newTitle.trim();
    refreshConvList();
  });

  delBtn.addEventListener("click", async e => {
    e.stopPropagation();
    if (!confirm(`删除对话「${conv.title}」？`)) return;
    await fetch(`/api/conversations/${conv.id}`, { method: "DELETE", headers: apiHeaders() });
    if (conv.id === activeConvId) {
      activeConvId = null;
      history = [];
      messagesEl.innerHTML = `<div class="welcome" id="welcome">${WELCOME_HTML}</div>`;
      chatTitle.textContent = "对话";
      bindSuggestions();
    }
    refreshConvList();
  });

  return item;
}

function highlightActiveConv() {
  convListEl.querySelectorAll(".conv-item").forEach(el => {
    el.classList.toggle("active", el.dataset.convId === activeConvId);
  });
}

newConvBtn.addEventListener("click", async () => {
  const conv = await createConversation();
  if (!conv) return;
  messagesEl.innerHTML = `<div class="welcome" id="welcome">${WELCOME_HTML}</div>`;
  bindSuggestions();
  await refreshConvList();
  closeSidebar();
});

// ── 移动端侧边栏 ──────────────────────────────────────────────────────────────
function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.remove("show");
}

hamburgerBtn?.addEventListener("click", () => {
  sidebar.classList.toggle("open");
  sidebarOverlay.classList.toggle("show");
});
sidebarOverlay?.addEventListener("click", closeSidebar);

// ── 认证 ──────────────────────────────────────────────────────────────────────
async function initAuth() {
  const tok = getAuthToken();
  if (tok) {
    try {
      const res = await fetch("/api/auth/me", { headers: { "Authorization": `Bearer ${tok}` } });
      const data = await res.json();
      if (data.username) { showLoggedIn(data.username); return; }
    } catch { /* fallthrough */ }
    clearAuthToken();
  }
  showLoggedOut();
}

function showLoggedIn(username) {
  authSection.style.display = "none";
  userSection.style.display = "flex";
  currentUser.textContent = username;
}

function showLoggedOut() {
  authSection.style.display = "block";
  userSection.style.display = "none";
}

async function doAuth(endpoint) {
  const username = usernameInput.value.trim();
  if (!username) { showError("请输入用户名"); return; }
  try {
    const res = await fetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, guest_id: getGuestId() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "操作失败");
    setAuthToken(data.token);
    showLoggedIn(data.username);
    usernameInput.value = "";
    await refreshConvList();
    // 重新加载最近对话
    const listRes = await fetch("/api/conversations", { headers: apiHeaders() });
    const listData = await listRes.json();
    const firstGroup = Object.values(listData.groups || {})[0];
    if (firstGroup?.length) loadConversation(firstGroup[0].id);
  } catch (err) {
    showError(err.message);
  }
}

registerBtn.addEventListener("click", () => doAuth("/api/auth/register"));
loginBtn.addEventListener("click",    () => doAuth("/api/auth/login"));

logoutBtn.addEventListener("click", () => {
  clearAuthToken();
  showLoggedOut();
  activeConvId = null;
  history = [];
  messagesEl.innerHTML = `<div class="welcome" id="welcome">${WELCOME_HTML}</div>`;
  chatTitle.textContent = "对话";
  bindSuggestions();
  refreshConvList();
});

// ── 建议词 ────────────────────────────────────────────────────────────────────
function bindSuggestions() {
  document.querySelectorAll(".suggestion").forEach(btn => {
    btn.addEventListener("click", () => sendMessage(btn.dataset.prompt));
  });
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
async function init() {
  await initAuth();
  await refreshConvList();

  // 加载最近对话
  const listRes = await fetch("/api/conversations", { headers: apiHeaders() });
  const listData = await listRes.json();
  const firstGroup = Object.values(listData.groups || {})[0];
  if (firstGroup?.length) {
    await loadConversation(firstGroup[0].id);
  }

  bindSuggestions();
  checkHealth();
  setInterval(checkHealth, 15000);
}

init();
