const bridge = window.AstrBotPluginPage;
await bridge.ready();

const $ = (id) => document.getElementById(id);
const toastEl = $("toast");

const TYPE = [
  { key: "text_type", label: "文本", icon: "📝", badge: "badge-text" },
  { key: "img_type", label: "图片", icon: "🖼️", badge: "badge-img" },
  { key: "audio_type", label: "音频", icon: "🎵", badge: "badge-audio" },
  { key: "video_type", label: "视频", icon: "🎬", badge: "badge-video" },
];
const TRIGGER = { global: "全局", direct: "直接", mention_only: "仅@" };
const VIEWS = { overview: "API 总览", config: "API 配置", stats: "调用统计" };

let currentView = "overview";
let allApis = [];
let globalConfig = {};

// ── Toast ──
function toast(msg, type = "success") {
  toastEl.textContent = msg;
  toastEl.className = `toast toast-${type} show`;
  setTimeout(() => { toastEl.className = `toast toast-${type}`; }, 2000);
}

// ── Navigation ──
function switchView(view) {
  currentView = view;
  $("pageTitle").textContent = VIEWS[view];
  document.querySelectorAll(".nav-item").forEach(item => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  if (view === "overview") loadOverview();
  else if (view === "config") loadConfig();
  else if (view === "stats") loadStats();
}

document.querySelectorAll(".nav-item").forEach(item => {
  item.addEventListener("click", () => switchView(item.dataset.view));
});

// ── Theme toggle ──
$("themeToggleBtn").addEventListener("click", () => {
  const html = document.documentElement;
  const current = html.getAttribute("data-theme") || "light";
  const next = current === "light" ? "dark" : "light";
  html.setAttribute("data-theme", next);
});

// ── Helpers ──
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function fmtJson(obj) {
  if (!obj || !Object.keys(obj).length) return '<span style="color:var(--text-secondary)">(空)</span>';
  return `<pre>${esc(JSON.stringify(obj, null, 2))}</pre>`;
}

// ── Overview ──
async function loadOverview() {
  $("content").innerHTML = '<div class="loading">加载中...</div>';
  $("topbarActions").innerHTML = '';
  try {
    const data = await bridge.apiGet("overview/data");
    renderOverview(data.custom_apis || []);
  } catch (e) {
    $("content").innerHTML = `<div class="empty">加载失败: ${e.message || e}</div>`;
  }
}

function renderOverview(apis) {
  const grouped = {}; TYPE.forEach(t => grouped[t.key] = []);
  apis.forEach(a => { const k = a.__template_key || "text_type"; if (grouped[k]) grouped[k].push(a); });

  let html = `<div class="stats-bar">`;
  html += `<div class="stat-card"><div class="label">API 总数</div><div class="value">${apis.length}</div></div>`;
  TYPE.forEach(t => {
    html += `<div class="stat-card"><div class="label">${t.label} API</div><div class="value">${grouped[t.key].length}</div></div>`;
  });
  html += `</div>`;

  for (const t of TYPE) {
    const items = grouped[t.key];
    html += `<div class="section"><div class="section-header"><div class="section-title">${t.icon} ${t.label} API <span class="count">（${items.length}）</span></div></div>`;
    if (!items.length) {
      html += `<div class="empty">暂无 ${t.label} API 配置</div>`;
    } else {
      html += `<div class="api-grid">`;
      for (const api of items) {
        const urls = Array.isArray(api.api_url) ? api.api_url : [api.api_url].filter(Boolean);
        html += `<div class="api-card">
          <div class="cmd">/${api.api_name || '-'}</div>
          <div class="meta-row"><span class="badge ${t.badge}">${t.label}</span> <span class="label">触发方式</span> ${TRIGGER[api.trigger_type] || "全局"}</div>
          <div class="meta-row"><span class="label">请求</span> ${api.method || 'GET'} <span class="label">超时</span> ${api.timeout || '默认'}s <span class="label">频率</span> ${api.api_rate_limit || '继承全局'}/min</div>
          <div class="url-list">${urls.map(u => `<span class="url-tag" title="${esc(u)}">${esc(u)}</span>`).join('') || '<span style="font-size:0.75rem;color:var(--text-secondary)">未配置URL</span>'}</div>
        </div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  $("content").innerHTML = html;
}

// ── Config ──
async function loadConfig() {
  $("content").innerHTML = '<div class="loading">加载中...</div>';
  $("topbarActions").innerHTML = `<button class="btn btn-primary" id="exportBtn">导出 JSON</button>`;
  try {
    [allApis, globalConfig] = await Promise.all([
      bridge.apiGet("config/list"),
      bridge.apiGet("config/global"),
    ]);
    if (!Array.isArray(allApis)) allApis = [];
    renderConfig();
  } catch (e) {
    $("content").innerHTML = `<div class="empty">加载失败: ${e.message || e}</div>`;
  }
}

function renderConfig() {
  let html = '';

  // Global config
  html += `<div class="section"><div class="section-header"><div class="section-title">⚙️ 全局配置</div><button class="btn btn-primary" id="saveGlobalBtn">保存</button></div>`;
  html += `<div class="global-form"><div class="form-row">
    <div class="form-group"><label>全局超时（秒）</label><input type="number" id="globalTimeout" min="1" max="120" value="${globalConfig.global_default_timeout || 15}" /></div>
    <div class="form-group"><label>全局频率限制（次/分，0=不限）</label><input type="number" id="globalRateLimit" min="0" value="${globalConfig.global_rate_limit || 0}" /></div>
    <div class="form-group"><label>默认触发方式</label><select id="defaultTriggerType"><option value="direct" ${globalConfig.default_trigger_type === 'direct' ? 'selected' : ''}>直接触发</option><option value="mention_only" ${globalConfig.default_trigger_type === 'mention_only' ? 'selected' : ''}>仅@触发</option></select></div>
  </div></div></div>`;

  // Categories
  for (const t of TYPE) {
    const items = allApis.filter(a => (a.__template_key || "text_type") === t.key);
    html += `<div class="section"><div class="section-header"><div class="section-title">${t.icon} ${t.label} API <span class="count">（${items.length}）</span></div><button class="btn btn-primary btn-sm add-api-btn" data-type="${t.key}">+ 新增</button></div>`;
    if (!items.length) {
      html += `<div class="empty">暂无配置</div>`;
    } else {
      html += `<div class="api-config-cards">`;
      for (let i = 0; i < allApis.length; i++) {
        const api = allApis[i];
        if ((api.__template_key || "text_type") !== t.key) continue;
        const urls = Array.isArray(api.api_url) ? api.api_url : [api.api_url].filter(Boolean);
        html += `<div class="api-config-card">
          <div class="info"><div class="cmd">/${api.api_name || '-'}</div><div class="meta"><span class="badge ${t.badge}">${t.label}</span> · ${api.method || 'GET'} · ${TRIGGER[api.trigger_type] || '全局'}</div><div class="url" title="${urls.join(', ')}">${urls[0] || '未配置URL'}</div></div>
          <div class="actions"><button class="btn btn-sm btn-muted edit-btn" data-idx="${i}">编辑</button><button class="btn btn-sm btn-danger del-btn" data-idx="${i}">删除</button><button class="btn btn-sm btn-info detail-btn" data-idx="${i}">详情</button></div>
        </div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  $("content").innerHTML = html;
  bindConfigEvents();
}

function bindConfigEvents() {
  $("saveGlobalBtn").addEventListener("click", async () => {
    try {
      await bridge.apiPost("config/save-global", {
        global_default_timeout: parseInt($("globalTimeout").value) || 15,
        global_rate_limit: parseInt($("globalRateLimit").value) || 0,
        default_trigger_type: $("defaultTriggerType").value,
      });
      toast("全局配置已保存");
    } catch (e) { toast("保存失败: " + (e.message || e), "error"); }
  });
  $("exportBtn").addEventListener("click", async () => {
    try { await bridge.download("config/export", {}, "api_config.json"); toast("配置已导出"); }
    catch (e) { toast("导出失败: " + (e.message || e), "error"); }
  });
  document.querySelectorAll(".add-api-btn").forEach(b => b.addEventListener("click", () => openAdd(b.dataset.type)));
  document.querySelectorAll(".edit-btn").forEach(b => b.addEventListener("click", () => openEdit(parseInt(b.dataset.idx))));
  document.querySelectorAll(".del-btn").forEach(b => b.addEventListener("click", () => deleteApi(parseInt(b.dataset.idx))));
  document.querySelectorAll(".detail-btn").forEach(b => b.addEventListener("click", () => showDetail(parseInt(b.dataset.idx))));
}

function openAdd(typeKey) {
  $("editIndex").value = "-1";
  $("editType").value = typeKey;
  $("editModalTitle").textContent = `新增 ${TYPE.find(t => t.key === typeKey)?.label || 'API'} API`;
  $("submitEditBtn").textContent = "创建";
  resetEditForm();
  openModal("editModal");
}
function openEdit(idx) {
  const api = allApis[idx];
  $("editIndex").value = idx;
  $("editType").value = api.__template_key || "text_type";
  $("editModalTitle").textContent = `编辑 /${api.api_name || ''}`;
  $("submitEditBtn").textContent = "更新";
  $("editApiName").value = api.api_name || "";
  $("editMethod").value = api.method || "GET";
  $("editTriggerType").value = api.trigger_type || "global";
  $("editApiUrl").value = Array.isArray(api.api_url) ? api.api_url.join(", ") : (api.api_url || "");
  $("editTimeout").value = api.timeout || 0;
  $("editRateLimit").value = api.api_rate_limit || 0;
  $("editDataPath").value = api.data_path || "";
  $("editParams").value = api.params && Object.keys(api.params).length ? JSON.stringify(api.params, null, 2) : "";
  $("editHeaders").value = api.headers && Object.keys(api.headers).length ? JSON.stringify(api.headers, null, 2) : "";
  $("editBody").value = api.body && Object.keys(api.body).length ? JSON.stringify(api.body, null, 2) : "";
  openModal("editModal");
}
function resetEditForm() {
  $("editApiName").value = ""; $("editMethod").value = "GET"; $("editTriggerType").value = "global";
  $("editApiUrl").value = ""; $("editTimeout").value = "0"; $("editRateLimit").value = "0";
  $("editDataPath").value = ""; $("editParams").value = ""; $("editHeaders").value = ""; $("editBody").value = "";
}

$("editForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("submitEditBtn").disabled = true;
  const typeKey = $("editType").value;
  const urls = $("editApiUrl").value.split(",").map(s => s.trim()).filter(Boolean);
  const payload = {
    __template_key: typeKey,
    api_name: $("editApiName").value.trim(),
    api_url: urls,
    method: $("editMethod").value,
    timeout: parseInt($("editTimeout").value) || 0,
    api_rate_limit: parseInt($("editRateLimit").value) || 0,
    trigger_type: $("editTriggerType").value,
    data_path: $("editDataPath").value.trim(),
  };
  for (const f of ["params", "headers", "body"]) {
    const raw = $(`edit${f.charAt(0).toUpperCase() + f.slice(1)}`).value.trim();
    if (raw) { try { payload[f] = JSON.parse(raw); } catch (err) { toast(`${f} JSON 错误: ${err.message}`, "error"); $("submitEditBtn").disabled = false; return; } }
    else { payload[f] = f === "body" ? {} : {}; }
  }
  const editIdx = parseInt($("editIndex").value);
  try {
    if (editIdx >= 0) { await bridge.apiPost("config/update", { index: editIdx, config: payload }); toast("API 已更新"); }
    else { await bridge.apiPost("config/add", { config: payload }); toast("API 已创建"); }
    closeModal("editModal");
    await loadConfig();
  } catch (err) { toast("保存失败: " + (err.message || err), "error"); }
  finally { $("submitEditBtn").disabled = false; }
});

async function deleteApi(idx) {
  if (!confirm(`确定要删除 /${allApis[idx]?.api_name || '此API'} 吗？`)) return;
  try { await bridge.apiPost("config/delete", { index: idx }); toast("已删除"); await loadConfig(); }
  catch (e) { toast("删除失败: " + (e.message || e), "error"); }
}

function showDetail(idx) {
  const api = allApis[idx];
  const t = TYPE.find(t => t.key === (api.__template_key || "text_type"));
  const urls = Array.isArray(api.api_url) ? api.api_url.map(u => `<code>${esc(u)}</code>`).join("<br>") : (api.api_url || "-");
  $("detailContent").innerHTML = `<dl class="detail-grid">
    <dt>类型</dt><dd><span class="badge ${t?.badge || ''}">${t?.label || '-'}</span></dd>
    <dt>触发命令</dt><dd><strong>/${api.api_name || '-'}</strong></dd>
    <dt>请求方式</dt><dd>${api.method || 'GET'}</dd>
    <dt>触发方式</dt><dd>${TRIGGER[api.trigger_type] || '全局'}</dd>
    <dt>超时</dt><dd>${api.timeout || '默认'}s</dd>
    <dt>频率限制</dt><dd>${api.api_rate_limit || '继承全局'}/min</dd>
    <dt>数据路径</dt><dd><code>${api.data_path || '(无)'}</code></dd>
    <dt>请求参数</dt><dd>${fmtJson(api.params)}</dd>
    <dt>请求头</dt><dd>${fmtJson(api.headers)}</dd>
    <dt>请求体</dt><dd>${fmtJson(api.body)}</dd>
    <dt>API 地址</dt><dd>${urls}</dd>
  </dl>`;
  openModal("detailModal");
}

// ── Stats ──
async function loadStats() {
  $("content").innerHTML = '<div class="loading">加载中...</div>';
  $("topbarActions").innerHTML = `<button class="btn btn-primary" id="refreshBtn">刷新数据</button>`;
  try {
    const data = await bridge.apiGet("stats/data");
    renderStats(data);
  } catch (e) {
    $("content").innerHTML = `<div class="empty">加载失败: ${e.message || e}</div>`;
  }
}

function renderStats(data) {
  const { total_calls, api_stats, user_stats } = data;
  const uniqueApis = Object.keys(api_stats || {}).length;
  const uniqueUsers = Object.keys(user_stats || {}).length;
  let html = `<div class="stats-bar">`;
  html += `<div class="stat-card"><div class="label">60s 内总调用</div><div class="value">${total_calls || 0}</div></div>`;
  html += `<div class="stat-card"><div class="label">活跃 API</div><div class="value">${uniqueApis}</div></div>`;
  html += `<div class="stat-card"><div class="label">活跃用户</div><div class="value">${uniqueUsers}</div></div>`;
  html += `</div>`;
  html += `<div class="grid-2"><div class="section"><div class="section-title">按 API 统计</div>${renderTable(api_stats, "API 指令", "总调用数")}</div><div class="section"><div class="section-title">按用户统计</div>${renderTable(user_stats, "用户", "总请求数")}</div></div>`;
  $("content").innerHTML = html;
  $("refreshBtn").addEventListener("click", loadStats);
}

function renderTable(stats, keyLabel, valLabel) {
  const entries = Object.entries(stats || {});
  if (!entries.length) return '<div class="empty">暂无数据</div>';
  entries.sort((a, b) => b[1] - a[1]);
  const max = entries[0][1] || 1;
  let html = `<table><thead><tr><th>${keyLabel}</th><th>${valLabel}</th><th>占比</th></tr></thead><tbody>`;
  for (const [key, cnt] of entries) {
    const pct = Math.round((cnt / max) * 100);
    const cls = pct > 80 ? 'danger' : (pct > 50 ? 'warn' : '');
    html += `<tr><td><strong>${esc(key)}</strong></td><td>${cnt}</td><td><div class="bar-wrapper"><div class="bar-bg"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div><span class="bar-num">${pct}%</span></div></td></tr>`;
  }
  html += `</tbody></table>`;
  return html;
}

// ── Modal helpers ──
function openModal(id) { $(id).classList.add("open"); }
function closeModal(id) { $(id).classList.remove("open"); }
$("closeEditModal").addEventListener("click", () => closeModal("editModal"));
$("cancelEditBtn").addEventListener("click", () => closeModal("editModal"));
$("closeDetailModal").addEventListener("click", () => closeModal("detailModal"));
$("editModal").addEventListener("click", (e) => { if (e.target === $("editModal")) closeModal("editModal"); });
$("detailModal").addEventListener("click", (e) => { if (e.target === $("detailModal")) closeModal("detailModal"); });

// ── Init ──
switchView("overview");
