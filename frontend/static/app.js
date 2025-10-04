const API = "/api/chat/";
const LS_KEY = "lawbot_sessions_v1";

const $ = s => document.querySelector(s);

const els = {
  list: $("#session-list"),
  msgs: $("#messages"),
  input: $("#q"),
  send: $("#send"),
  newChat: $("#new-chat"),
  title: $(".chat-title"),
  sub: $(".chat-sub"),
  confirm: $("#confirm"),
  confirmOk: $("#confirm-ok"),
  confirmCancel: $("#confirm-cancel"),
};

let sessions = loadSessions();
let currentId = ensureCurrentSession();
let pendingDeleteId = null;

renderSessionList();
renderCurrentSession();

/* ===== 本地存储 ===== */
function loadSessions() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; }
}
function saveSessions() { localStorage.setItem(LS_KEY, JSON.stringify(sessions)); }
function ensureCurrentSession() {
  const ids = Object.keys(sessions);
  if (ids.length) return ids.sort((a,b)=>sessions[b].updatedAt - sessions[a].updatedAt)[0];
  return createSession("新会话");
}
function createSession(title){
  const id = "s" + Date.now();
  sessions[id] = { id, title, updatedAt: Date.now(), messages: [] };
  saveSessions();
  return id;
}

/* ===== 渲染会话列表 ===== */
function renderSessionList() {
  els.list.innerHTML = "";
  const ids = Object.keys(sessions).sort((a,b)=>sessions[b].updatedAt - sessions[a].updatedAt);
  ids.forEach(id => {
    const s = sessions[id];
    const div = document.createElement("div");
    div.className = "session" + (id === currentId ? " active" : "");
    div.onclick = () => { currentId = id; renderSessionList(); renderCurrentSession(); };

    const last = s.messages.length
      ? (s.messages.findLast ? s.messages.findLast(m=>m.role==="user") : [...s.messages].reverse().find(m=>m.role==="user"))
      : null;

    div.innerHTML = `
      <div class="session-title">${escapeHtml(s.title || "(未命名)")}</div>
      <div class="session-sub">${escapeHtml(last ? trimForPreview(last.text) : "（未检索到相关的标准，以下为模型通用回答）")}</div>
      <button class="del" title="删除会话" aria-label="删除会话">🗑</button>
    `;
    const delBtn = div.querySelector(".del");
    delBtn.addEventListener("click", (e)=>{ e.stopPropagation(); askDelete(id); });

    els.list.appendChild(div);
  });
}

/* ===== 渲染消息 ===== */
function renderCurrentSession() {
  const s = sessions[currentId];
  els.msgs.innerHTML = "";
  els.title.textContent = "LawBot • AI assistance";
  els.sub.textContent = "";
  s.messages.forEach(m => appendBubble(m.role, m.text, m.meta));
  scrollBottom();
}

function appendBubble(role, text, meta){
  const wrap = document.createElement("div");
  wrap.className = "msg " + (role === "user" ? "user" : "bot");
  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role === "bot") {
    bubble.innerHTML = text;   // 关键：渲染包含 <a> 的 HTML
  } else {
    bubble.textContent = text; // 用户消息仍然用纯文本
  }

  wrap.appendChild(bubble);
  els.msgs.appendChild(wrap);

  if (meta){
    const info = document.createElement("div");
    info.className = "meta";
    info.textContent = meta;
    els.msgs.appendChild(info);
  }
}


/* ===== 发送 ===== */
async function send(){
  const question = els.input.value.trim();
  if (!question) return;
  const s = sessions[currentId];

  appendBubble("user", question);
  s.messages.push({role:"user", text:question});
  s.updatedAt = Date.now();
  saveSessions();
  renderSessionList();
  els.input.value = "";
  lock(true);

  try{
    const res = await fetch(API, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({question, session_id: currentId})
    });

    const ct = res.headers.get("content-type") || "";
    const raw = await res.text();
    let data = null;
    if (ct.includes("application/json")) {
      try { data = JSON.parse(raw); } catch {}
    }

    if (!res.ok) {
      const msg = (data && data.error) ? data.error : raw.slice(0,200);
      appendBubble("bot", "出错：" + msg);
      s.messages.push({role:"bot", text:"出错：" + msg});
    } else {
      if (!data) {
        appendBubble("bot", "出错：后端未返回 JSON");
        s.messages.push({role:"bot", text:"出错：后端未返回 JSON"});
      } else {
        const meta = `used_retrieval=${data.used_retrieval}  score=${data.score}`;
        appendBubble("bot", data.text || "(无内容)", meta);
        s.messages.push({role:"bot", text:data.text || "(无内容)", meta});
        if(!s.title || s.title==="新会话") s.title = trimForTitle(question);
      }
    }
  }catch(e){
    appendBubble("bot","网络错误：" + e.message);
    s.messages.push({role:"bot", text:"网络错误：" + e.message});
  }finally{
    s.updatedAt = Date.now();
    saveSessions();
    renderSessionList();
    lock(false);
    scrollBottom();
  }
}

function lock(disabled){
  els.send.disabled = disabled;
  els.input.disabled = disabled;
}
function scrollBottom(){ els.msgs.scrollTop = els.msgs.scrollHeight; }

/* ===== 删除会话 ===== */
function askDelete(id){
  pendingDeleteId = id;
  els.confirm.classList.remove("hidden");
}
function closeConfirm(){
  pendingDeleteId = null;
  els.confirm.classList.add("hidden");
}
function deleteSession(id){
  if(!sessions[id]) return;
  delete sessions[id];
  const ids = Object.keys(sessions).sort((a,b)=>sessions[b].updatedAt - sessions[a].updatedAt);
  currentId = ids[0] || createSession("新会话");
  saveSessions();
  renderSessionList();
  renderCurrentSession();
}

/* ===== 工具 ===== */
function escapeHtml(s){ return s.replace(/[&<>"']/g, c=>({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[c])); }
function trimForPreview(s){ return s.length>36 ? s.slice(0,36)+"…" : s; }
function trimForTitle(s){ return s.length>24 ? s.slice(0,24)+"…" : s; }

/* ===== 事件 ===== */
els.send.addEventListener("click", send);
els.input.addEventListener("keydown", e => { if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); send(); } });
els.newChat.addEventListener("click", ()=>{
  currentId = createSession("新会话");
  renderSessionList();
  renderCurrentSession();
  els.input.focus();
});
els.confirmOk.addEventListener("click", ()=>{ if(pendingDeleteId){ deleteSession(pendingDeleteId); } closeConfirm(); });
els.confirmCancel.addEventListener("click", closeConfirm);
els.confirm.addEventListener("click", (e)=>{ if(e.target===els.confirm) closeConfirm(); });
