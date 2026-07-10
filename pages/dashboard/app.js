const bridge = window.AstrBotPluginPage;
await bridge.ready();

const $ = (id) => document.getElementById(id);

const TYPE = [
  { key: "text_type", label: "文本 API", icon: "📝", cls: "type-text", badge: "badge-text" },
  { key: "img_type",  label: "图片 API", icon: "🖼️", cls: "type-img", badge: "badge-img" },
  { key: "audio_type", label: "音频 API", icon: "🎵", cls: "type-audio", badge: "badge-audio" },
  { key: "video_type", label: "视频 API", icon: "🎬", cls: "type-video", badge: "badge-video" },
];
const TRIGGER = { global: "全局", direct: "直接", mention_only: "仅@" };
const RANGE_LABELS = { today: "今日", month: "本月", total: "总计" };

let allApis = [];
let globalConfig = {};
let currentView = "overview";
let overviewEventsBound = false;

// Test 视图状态
const testState = {
  editIndex: -1,  // -1 表示新增，>=0 表示编辑
  config: null,   // 预填配置
};

// Overview 视图状态：切换时保留用户选择
const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const overviewState = {
  topApiRange: "today",
  topUserRange: "today",
  apiTrendMonth: currentMonth(),
  userTrendMonth: currentMonth(),
};

// ── Toast ──
const toastEl = $("toast");
function toast(msg, type = "success") {
  toastEl.textContent = msg;
  toastEl.className = `toast toast-${type} show`;
  setTimeout(() => { toastEl.className = `toast toast-${type}`; }, 2000);
}
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

// ── Navigation ──
const navItems = document.querySelectorAll(".nav-item");
navItems.forEach(item => {
  item.addEventListener("click", () => {
    navItems.forEach(n => n.classList.remove("active"));
    item.classList.add("active");
    currentView = item.dataset.view;
    if (currentView === "test") {
      testState.editIndex = -1;
      testState.config = null;
    }
    loadView(currentView);
  });
});

async function loadView(view) {
  if (view === "overview") await loadOverview();
  else if (view === "config") await loadConfig();
  else if (view === "test") loadTest(testState.config, testState.editIndex);
}

// ── Theme toggle ──
$("themeToggleBtn").addEventListener("click", () => {
  const html = document.documentElement;
  const current = html.getAttribute("data-theme") || "light";
  html.setAttribute("data-theme", current === "dark" ? "light" : "dark");
});

// 顶部操作栏按钮委托（刷新按钮）
$("topbarActions").addEventListener("click", (e) => {
  const btn = e.target.closest("#refreshOverviewBtn");
  if (!btn) return;
  loadOverview();
});

// ── Overview ──
async function loadOverview() {
  $("pageTitle").textContent = "API 总览";
  $("topbarActions").innerHTML = `<button class="btn btn-primary" id="refreshOverviewBtn" title="刷新数据">🔄 刷新</button>`;
  $("content").innerHTML = '<div class="loading">加载中...</div>';
  try {
    const [overviewData, statsSummary, topApis, topUsers, apiTrend, userTrend] = await Promise.all([
      bridge.apiGet("overview/data"),
      bridge.apiGet("stats/summary"),
      bridge.apiGet("stats/top-apis", { range: overviewState.topApiRange }),
      bridge.apiGet("stats/top-users", { range: overviewState.topUserRange }),
      bridge.apiGet("stats/trend", { type: "calls", month: overviewState.apiTrendMonth }),
      bridge.apiGet("stats/trend", { type: "users", month: overviewState.userTrendMonth }),
    ]);
    renderOverview(
      overviewData.custom_apis || [],
      statsSummary,
      topApis.items || [],
      topUsers.items || [],
      apiTrend,
      userTrend
    );
  } catch (e) {
    $("content").innerHTML = `<div class="empty">加载失败: ${e.message || e}</div>`;
  }
}

function renderOverview(apis, stats, topApis, topUsers, apiTrend, userTrend) {
  const grouped = {};
  TYPE.forEach(t => { grouped[t.key] = []; });
  apis.forEach(a => { const k = a.__template_key || "text_type"; if (grouped[k]) grouped[k].push(a); });

  let html = `<div class="overview-top">
    <div class="api-count-panel">
      <div class="api-count-total">
        <div class="big-num">${apis.length}</div>
        <div class="big-label">API 总数</div>
      </div>
      <div class="type-grid">
        ${TYPE.map(t => `<div class="type-card ${t.cls}"><div class="label">${t.label}</div><div class="value">${grouped[t.key].length}</div></div>`).join("")}
      </div>
    </div>
    <div class="stats-grid">
      <div class="stats-card"><div class="label">累计调用次数</div><div class="value">${stats.total_calls || 0}</div></div>
      <div class="stats-card"><div class="label">今日调用次数</div><div class="value">${stats.today_calls || 0}</div></div>
      <div class="stats-card"><div class="label">累计用户数量</div><div class="value">${stats.total_users || 0}</div></div>
      <div class="stats-card"><div class="label">今日用户数量</div><div class="value">${stats.today_users || 0}</div></div>
    </div>
  </div>`;

  // 中部：左侧热门 API，右侧用户排行榜
  html += `<div class="ranking-section">
    ${renderTopSection("topApis", "🔥 热门 API", topApis, overviewState.topApiRange, "api")}
    ${renderTopSection("topUsers", "👤 用户调用次数", topUsers, overviewState.topUserRange, "user")}
  </div>`;

  // 底部：可切换月份的趋势图
  html += renderTrendSection("apiTrend", "API 调用次数", apiTrend, "calls", overviewState.apiTrendMonth, "accent");
  html += renderTrendSection("userTrend", "活跃用户数量", userTrend, "users", overviewState.userTrendMonth, "warning");

  $("content").innerHTML = html;
  attachChartTooltip("apiTrend");
  attachChartTooltip("userTrend");
  attachOverviewEvents();
}

function renderTopSection(id, title, items, currentRange, type) {
  const tabs = ["today", "month", "total"].map(r => {
    const cls = r === currentRange ? "tab active" : "tab";
    return `<button class="${cls}" data-range="${r}" data-type="${type}">${RANGE_LABELS[r]}</button>`;
  }).join("");

  let listHtml;
  if (!items.length) {
    listHtml = `<div class="empty" style="padding:20px;">暂无数据</div>`;
  } else {
    listHtml = `<div class="rank-list">`;
    items.forEach((item, idx) => {
      const name = type === "api" ? esc(item.name) : esc(item.user_id || "未知用户");
      const sub = type === "api" ? "调用" : "次";
      listHtml += `
        <div class="rank-item">
          <div class="rank-left">
            <span class="rank-num">${idx + 1}</span>
            <span class="rank-name">${name}</span>
          </div>
          <span class="rank-count">${item.count} ${sub}</span>
        </div>`;
    });
    listHtml += `</div>`;
  }

  return `<div class="rank-panel" id="${id}">
    <div class="section-header">
      <div class="section-title">${title}</div>
      <div class="range-tabs">${tabs}</div>
    </div>
    <div class="rank-body">${listHtml}</div>
  </div>`;
}

function renderTrendSection(id, title, response, trendType, currentMonth, colorVar) {
  const data = response && Array.isArray(response.data) ? response.data : (Array.isArray(response) ? response : []);
  const debug = response?.debug;
  const months = last12Months();
  const options = months.map(m => {
    const selected = m === currentMonth ? "selected" : "";
    return `<option value="${m}" ${selected}>${m}</option>`;
  }).join("");

  let debugHtml = "";
  if (!data.length && debug) {
    debugHtml = `<details style="margin-top:12px;font-size:0.75rem;color:var(--text-secondary);">
      <summary>诊断信息</summary>
      <pre style="background:var(--bg);padding:10px;border-radius:4px;overflow:auto;margin-top:8px;">${esc(JSON.stringify(debug, null, 2))}</pre>
    </details>`;
  }

  return `<div class="section" id="${id}">
    <div class="section-header">
      <div class="section-title">${title}</div>
      <select class="month-select" data-type="${trendType}">${options}</select>
    </div>
    <div class="chart-wrap" data-type="${trendType}">
      ${renderLineChart(data, colorVar, id)}
    </div>
    ${debugHtml}
  </div>`;
}

function last12Months() {
  const list = [];
  const now = new Date();
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    list.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return list;
}

function renderLineChart(data, colorVar, chartId) {
  if (!data.length) return '<div class="empty">暂无数据</div>';
  const maxVal = Math.max(...data.map(d => d.count), 1);
  const W = 860, H = 240, PAD = { top: 20, right: 20, bottom: 32, left: 48 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const pts = data.map((d, i) => {
    const x = PAD.left + (i / Math.max(data.length - 1, 1)) * plotW;
    const y = PAD.top + plotH - (d.count / maxVal * plotH);
    return `${x},${y}`;
  }).join(" ");

  const step = Math.max(1, Math.ceil(data.length / 10));
  const xLabels = data.map((d, i) => {
    if (i % step === 0) {
      const x = PAD.left + (i / Math.max(data.length - 1, 1)) * plotW;
      return `<text x="${x}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--text-secondary)">${d.date.slice(8)}</text>`;
    }
    return "";
  }).join("");

  const ySteps = 4;
  let yLabels = "";
  for (let i = 0; i <= ySteps; i++) {
    const val = Math.round((maxVal / ySteps) * i);
    const y = PAD.top + plotH - (i / ySteps) * plotH;
    yLabels += `<text x="${PAD.left - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="var(--text-secondary)">${val}</text>`;
    if (i > 0) {
      yLabels += `<line x1="${PAD.left}" y1="${y}" x2="${W - PAD.right}" y2="${y}" stroke="var(--border)" stroke-width="1" stroke-dasharray="4,3" />`;
    }
  }

  const fillPts = `${PAD.left},${PAD.top + plotH} ${pts} ${PAD.left + plotW},${PAD.top + plotH}`;
  const colorMap = { accent: "var(--accent)", warning: "var(--warning)", success: "var(--success)" };
  const lineColor = colorMap[colorVar] || "var(--accent)";

  const dots = data.map((d, i) => {
    const x = PAD.left + (i / Math.max(data.length - 1, 1)) * plotW;
    const y = PAD.top + plotH - (d.count / maxVal * plotH);
    return `<circle cx="${x}" cy="${y}" r="3.5" fill="${lineColor}" class="chart-dot" data-date="${d.date}" data-count="${d.count}" />`;
  }).join("");

  return `<svg id="${chartId}-svg" class="chart-svg" viewBox="0 0 ${W} ${H}" data-max="${maxVal}" data-pad='${JSON.stringify(PAD)}' data-w="${W}" data-h="${H}" data-len="${data.length}" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="grad-${chartId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${lineColor}" stop-opacity="0.25" />
        <stop offset="100%" stop-color="${lineColor}" stop-opacity="0.02" />
      </linearGradient>
    </defs>
    <line x1="${PAD.left}" y1="${PAD.top}" x2="${PAD.left}" y2="${PAD.top + plotH}" stroke="var(--border)" stroke-width="1" />
    <line x1="${PAD.left}" y1="${PAD.top + plotH}" x2="${W - PAD.right}" y2="${PAD.top + plotH}" stroke="var(--border)" stroke-width="1" />
    ${yLabels}
    ${xLabels}
    <polygon points="${fillPts}" fill="url(#grad-${chartId})" />
    <polyline points="${pts}" fill="none" stroke="${lineColor}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />
    ${dots}
  </svg>`;
}

function attachOverviewEvents() {
  const content = $("content");
  if (!content || overviewEventsBound) return;
  overviewEventsBound = true;

  // 使用事件委托，避免重复绑定
  content.addEventListener("click", async (e) => {
    const btn = e.target.closest(".range-tabs .tab");
    if (!btn) return;
    const type = btn.dataset.type; // 'api' or 'user'
    const range = btn.dataset.range;
    if (type === "api") overviewState.topApiRange = range;
    else overviewState.topUserRange = range;

    try {
      const endpoint = type === "api" ? "stats/top-apis" : "stats/top-users";
      const res = await bridge.apiGet(endpoint, { range });
      const panelId = type === "api" ? "topApis" : "topUsers";
      const title = type === "api" ? "🔥 热门 API" : "👤 用户调用次数";
      const panel = $(panelId);
      if (panel) panel.outerHTML = renderTopSection(panelId, title, res.items || [], range, type);
    } catch (err) {
      toast("加载失败: " + (err.message || err), "error");
    }
  });

  content.addEventListener("change", async (e) => {
    const sel = e.target.closest(".month-select");
    if (!sel) return;
    const trendType = sel.dataset.type; // 'calls' or 'users'
    const month = sel.value;
    if (trendType === "calls") overviewState.apiTrendMonth = month;
    else overviewState.userTrendMonth = month;

    try {
      const res = await bridge.apiGet("stats/trend", { type: trendType, month });
      const section = sel.closest(".section");
      const chartWrap = section?.querySelector(".chart-wrap");
      const id = trendType === "calls" ? "apiTrend" : "userTrend";
      const color = trendType === "calls" ? "accent" : "warning";
      if (chartWrap) {
        const data = res && Array.isArray(res.data) ? res.data : (Array.isArray(res) ? res : []);
        chartWrap.innerHTML = renderLineChart(data, color, id);
        attachChartTooltip(id);
      }
    } catch (err) {
      toast("加载失败: " + (err.message || err), "error");
    }
  });

  // 事件委托已绑定到 content，chart tooltip 由 renderOverview 单独挂载
}

function attachChartTooltip(chartId) {
  const svg = $(`${chartId}-svg`);
  const tooltip = $("chartTooltip");
  if (!svg || !tooltip) return;
  const wrap = svg.closest(".chart-wrap");

  svg.addEventListener("mousemove", (e) => {
    const len = parseInt(svg.dataset.len, 10);
    const pad = JSON.parse(svg.dataset.pad);
    const W = parseInt(svg.dataset.w, 10);
    const plotW = W - pad.left - pad.right;

    // 使用 SVG 坐标变换，处理响应式缩放与留白
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());

    const plotX = svgP.x - pad.left;
    let idx = Math.round((plotX / plotW) * (len - 1));
    idx = Math.max(0, Math.min(len - 1, idx));

    const dots = svg.querySelectorAll(".chart-dot");
    const dot = dots[idx];
    if (!dot) return;

    const date = dot.dataset.date;
    const count = dot.dataset.count;

    tooltip.innerHTML = `<div class="tt-date">${date}</div><div class="tt-count">${count}</div>`;
    tooltip.style.opacity = "1";
    tooltip.style.left = `${e.clientX + 12}px`;
    tooltip.style.top = `${e.clientY - 30}px`;
  });

  svg.addEventListener("mouseleave", () => {
    tooltip.style.opacity = "0";
  });
}

// ── Test ──
function loadTest(preloadConfig = null, editIndex = -1) {
  $("pageTitle").textContent = "API 测试";
  $("topbarActions").innerHTML = "";
  testState.editIndex = editIndex;
  testState.config = preloadConfig;
  renderTest();
  attachTestEvents();
}

function renderTest() {
  const cfg = testState.config || {};
  const typeKey = cfg.__template_key || "text_type";
  const method = cfg.method || "GET";
  const urls = Array.isArray(cfg.api_url) ? cfg.api_url.join(", ") : (cfg.api_url || "");
  const params = cfg.params || {};
  const headers = cfg.headers || {};
  const body = cfg.body && Object.keys(cfg.body).length ? JSON.stringify(cfg.body, null, 2) : "";

  const typeOptions = TYPE.map(t => `<option value="${t.key}" ${typeKey === t.key ? 'selected' : ''}>${t.label}</option>`).join("");

  $("content").innerHTML = `<div class="section test-page">
    <div class="test-topbar">
      <div class="form-group narrow-field"><label>触发命令 <span class="req">*</span></label><input type="text" id="testApiName" value="${esc(cfg.api_name || "")}" placeholder="例如: weather" /></div>
      <div class="form-group narrow-field"><label>API 类型</label><select id="testType">${typeOptions}</select></div>
      <div class="form-group narrow-field"><label>请求方法</label><select id="testMethod"><option value="GET" ${method === "GET" ? 'selected' : ''}>GET</option><option value="POST" ${method === "POST" ? 'selected' : ''}>POST</option></select></div>
      <div class="form-group wide-field"><label>API 地址 <span class="req">*</span></label><input type="text" id="testApiUrl" value="${esc(urls)}" placeholder="https://api.example.com/endpoint" /></div>
      <div class="test-actions-inline">
        <button class="btn btn-success" id="runTestBtn">发送</button>
        <button class="btn btn-danger" id="clearTestBtn">清除</button>
        <button class="btn btn-primary" id="saveTestBtn">保存</button>
      </div>
    </div>
    <div class="test-main">
    <div class="test-form">
      <div class="form-row">
        <div class="form-group"><label>超时（秒，0=全局）</label><input type="number" id="testTimeout" value="${cfg.timeout || 0}" min="0" max="120" /></div>
        <div class="form-group"><label>频率限制（次/分钟，0=全局）</label><input type="number" id="testRateLimit" value="${cfg.api_rate_limit || 0}" min="0" max="999" /></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>触发方式</label><select id="testTriggerType">
          <option value="global" ${(cfg.trigger_type || "global") === "global" ? 'selected' : ''}>使用全局设置</option>
          <option value="direct" ${cfg.trigger_type === "direct" ? 'selected' : ''}>直接触发</option>
          <option value="mention_only" ${cfg.trigger_type === "mention_only" ? 'selected' : ''}>仅@触发</option>
        </select></div>
        <div class="form-group" style="flex:2;"><label>数据提取路径（dpath）</label><input type="text" id="testDataPath" value="${esc(cfg.data_path || "")}" placeholder="例如: data.items.0.url" /></div>
      </div>
      ${renderKVSection("testParams", "请求参数", params)}
      ${renderKVSection("testHeaders", "请求头", headers)}
      <div class="form-group" style="margin-top:12px;">
        <label>请求体（JSON，仅 POST）</label>
        <textarea id="testBody" rows="8" placeholder="{}">${esc(body)}</textarea>
      </div>
    </div>
    <div class="test-response">
      <div class="response-header">
        <span class="status">状态码：<b id="respStatus">-</b><span class="elapsed" id="respElapsed"></span></span>
        <div class="response-tools">
          <input type="text" id="findInput" placeholder="Find..." />
          <button class="btn btn-sm btn-primary" id="findPrevBtn" title="上一个">▲</button>
          <button class="btn btn-sm btn-primary" id="findNextBtn" title="下一个">▼</button>
          <button class="btn btn-sm btn-info" id="copyRespBtn">复制</button>
        </div>
      </div>
      <div class="response-body-wrap">
        <pre id="respBody" class="response-body">点击「发送」发送请求...</pre>
        <div class="image-preview">
          <div class="image-preview-header">
            <input type="text" id="previewUrl" class="preview-url" placeholder="经过 dpath 提取的 URL" />
            <button class="btn btn-primary btn-sm" id="showPreviewBtn">显示</button>
          </div>
          <div class="image-preview-body">
            <img id="previewImg" src="" alt="预览" style="display:none; cursor:pointer;" title="点击查看原图" />
            <div class="preview-placeholder">点击「显示」渲染图片</div>
            <div class="image-preview-tools" id="previewTools" style="display:none; margin-top:10px;">
              <button class="btn btn-sm btn-muted" id="downloadImgBtn">下载原图</button>
            </div>
          </div>
        </div>
      </div>
    </div>
    </div>
  </div>`;

  renderKVList("testParams", params);
  renderKVList("testHeaders", headers);
  attachKVEvents("testParams");
  attachKVEvents("testHeaders");
}

function renderKVSection(id, title, items) {
  return `<div class="kv-section">
    <div class="kv-title"><span>${title}</span> <button class="btn btn-sm btn-primary add-kv-btn" data-target="${id}">+ 添加</button></div>
    <div class="kv-list" id="${id}"></div>
  </div>`;
}

function renderKVList(containerId, items) {
  const container = $(containerId);
  if (!container) return;
  const arr = Object.entries(items || {});
  if (!arr.length) arr.push(["", ""]);
  container.innerHTML = arr.map(([k, v]) => `
    <div class="kv-row">
      <input type="text" class="kv-key" placeholder="key" value="${esc(k)}" />
      <input type="text" class="kv-val" placeholder="value" value="${esc(typeof v === 'object' ? JSON.stringify(v) : String(v))}" />
      <button class="btn btn-sm btn-danger remove-kv-btn">-</button>
    </div>
  `).join("");
}

function attachKVEvents(containerId) {
  const container = $(containerId);
  const addBtn = document.querySelector(`.add-kv-btn[data-target="${containerId}"]`);
  if (!container) return;

  container.addEventListener("click", (e) => {
    if (e.target.closest(".remove-kv-btn")) {
      const row = e.target.closest(".kv-row");
      if (row) row.remove();
    }
  });

  if (addBtn) {
    addBtn.addEventListener("click", () => addKVRow(container));
  }
}

function addKVRow(container) {
  const div = document.createElement("div");
  div.className = "kv-row";
  div.innerHTML = `<input type="text" class="kv-key" placeholder="key" /><input type="text" class="kv-val" placeholder="value" /><button class="btn btn-sm btn-danger remove-kv-btn">-</button>`;
  container.appendChild(div);
}

function collectKVData(containerId) {
  const container = $(containerId);
  if (!container) return {};
  const data = {};
  container.querySelectorAll(".kv-row").forEach(row => {
    const k = row.querySelector(".kv-key")?.value.trim();
    const v = row.querySelector(".kv-val")?.value.trim();
    if (k) data[k] = v;
  });
  return data;
}

function collectTestConfig() {
  const urls = $("testApiUrl").value.split(",").map(s => s.trim()).filter(Boolean);
  let body = {};
  const bodyRaw = $("testBody").value.trim();
  if (bodyRaw) {
    try { body = JSON.parse(bodyRaw); }
    catch (e) { toast("请求体 JSON 格式错误", "error"); throw e; }
  }
  const baseConfig = {
    __template_key: $("testType").value,
    api_name: $("testApiName").value.trim(),
    api_url: urls,
    method: $("testMethod").value,
    timeout: parseInt($("testTimeout").value) || 0,
    api_rate_limit: parseInt($("testRateLimit").value) || 0,
    trigger_type: $("testTriggerType").value,
    data_path: $("testDataPath").value.trim(),
    params: collectKVData("testParams"),
    headers: collectKVData("testHeaders"),
    body: body,
  };
  // 编辑时保留原配置中的类型专属字段（如 auto_preview、max_size 等）
  return testState.config ? { ...testState.config, ...baseConfig } : baseConfig;
}

function formatResponse(data) {
  if (data === null || data === undefined) return "(无数据)";
  if (typeof data === "string") return data;
  try { return JSON.stringify(data, null, 2); }
  catch (e) { return String(data); }
}

function attachTestEvents() {
  $("clearTestBtn")?.addEventListener("click", () => {
    testState.editIndex = -1;
    testState.config = null;
    renderTest();
  });

  $("runTestBtn")?.addEventListener("click", async () => {
    const config = collectTestConfig();
    if (!config.api_name || !config.api_url.length) {
      toast("触发命令和 API 地址不能为空", "error");
      return;
    }
    try {
      $("runTestBtn").disabled = true;
      $("respStatus").textContent = "-";
      $("respElapsed").textContent = "";
      $("respBody").textContent = "发送请求中...";
      const res = await bridge.apiPost("config/test", { config });
      $("respStatus").textContent = res.http_code ?? "-";
      const elapsed = res.elapsed_ms;
      $("respElapsed").textContent = elapsed != null ? ` | ${elapsed}ms` : "";
      const pre = $("respBody");
      const placeholder = document.querySelector(".preview-placeholder");
      const img = $("previewImg");
      const previewUrl = $("previewUrl");

      const isBinaryImage = res.media_type === "img" || (res.content_type && res.content_type.startsWith("image/"));
      if (isBinaryImage) {
        pre.textContent = "(二进制图片响应，已渲染在下方预览框)";
        pre.dataset.originalText = pre.textContent;
        const imageUrl = typeof res.response_data === "string" && res.response_data.startsWith("data:") ? res.response_data : String(res.response_data || "");
        img.src = imageUrl;
        img.style.display = "block";
        if (placeholder) placeholder.style.display = "none";
        const tools = $("previewTools");
        if (tools) tools.style.display = "flex";
      } else {
        const text = formatResponse(res.response_data);
        pre.textContent = text;
        pre.dataset.originalText = text;
        img.src = "";
        img.style.display = "none";
        if (placeholder) placeholder.style.display = "flex";
        const tools2 = $("previewTools");
        if (tools2) tools2.style.display = "none";

        // 自动按 data_path 提取内容填入单行文本框
        const dataPath = $("testDataPath").value.trim();
        if (dataPath) {
          let data = null;
          try { data = JSON.parse(text); } catch (e) {}
          if (data !== null) {
            const extracted = extractByPath(data, dataPath);
            if (extracted !== undefined && extracted !== null && extracted !== "") {
              if (previewUrl) previewUrl.value = String(extracted);
            }
          }
        }
      }
      pre.dataset.findIndex = "-1";
      delete pre.dataset.findTerm;
    } catch (e) {
      $("respStatus").textContent = "-";
      $("respBody").textContent = "测试失败: " + (e.message || e);
    } finally {
      $("runTestBtn").disabled = false;
    }
  });

  $("saveTestBtn")?.addEventListener("click", async () => {
    const config = collectTestConfig();
    if (!config.api_name || !config.api_url.length) {
      toast("触发命令和 API 地址不能为空", "error");
      return;
    }
    try {
      $("saveTestBtn").disabled = true;
      if (testState.editIndex >= 0) {
        await bridge.apiPost("config/update", { index: testState.editIndex, config });
        toast("API 已更新");
      } else {
        await bridge.apiPost("config/add", { config });
        toast("API 已创建");
      }
      await loadConfig();
    } catch (e) {
      toast("保存失败: " + (e.message || e), "error");
    } finally {
      $("saveTestBtn").disabled = false;
    }
  });

  $("copyRespBtn")?.addEventListener("click", () => {
    const text = $("respBody").textContent;
    navigator.clipboard.writeText(text).then(
      () => toast("已复制到剪贴板"),
      () => toast("复制失败", "error")
    );
  });

  $("findNextBtn")?.addEventListener("click", () => findInResponse("next"));
  $("findPrevBtn")?.addEventListener("click", () => findInResponse("prev"));
  $("findInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") findInResponse("next");
  });

  $("showPreviewBtn")?.addEventListener("click", () => {
    const urlStr = $("previewUrl").value.trim();
    if (!urlStr) {
      toast("请输入图片 URL", "error");
      return;
    }
    const img = $("previewImg");
    const placeholder = document.querySelector(".preview-placeholder");
    const tools = $("previewTools");
    img.src = urlStr;
    img.style.display = "block";
    if (placeholder) placeholder.style.display = "none";
    if (tools) tools.style.display = "flex";
  });

  // 点击图片放大（内嵌 lightbox）
  $("previewImg")?.addEventListener("click", () => {
    const src = $("previewImg").src;
    if (!src) return;
    $("lightboxImg").src = src;
    $("imgLightbox").classList.add("open");
  });

  // 下载图片
  $("downloadImgBtn")?.addEventListener("click", () => {
    const src = $("previewImg").src;
    if (!src) return;
    const a = document.createElement("a");
    a.href = src;
    a.download = "api_response." + (src.startsWith("data:") ? src.substring(5, src.indexOf(";")).replace("image/", "") : "png");
    a.click();
  });

  // lightbox 关闭
  $("closeLightbox")?.addEventListener("click", () => $("imgLightbox").classList.remove("open"));
  $("imgLightbox")?.addEventListener("click", (e) => {
    if (e.target === $("imgLightbox")) $("imgLightbox").classList.remove("open");
  });
}

function extractByPath(obj, path) {
  if (!path || obj === null || obj === undefined) return undefined;
  const keys = path.split(".");
  let current = obj;
  for (const key of keys) {
    if (current === null || current === undefined) return undefined;
    if (Array.isArray(current)) {
      const idx = parseInt(key);
      if (!isNaN(idx) && idx >= 0 && idx < current.length) current = current[idx];
      else return undefined;
    } else {
      current = current[key];
    }
  }
  return current;
}

function findInResponse(direction) {
  const pre = $("respBody");
  const input = $("findInput");
  if (!pre || !input) return;
  const term = input.value.trim();
  if (!term) return;

  let text = pre.textContent;
  // 如果已有高亮，先恢复原文本
  if (pre.dataset.originalText) text = pre.dataset.originalText;
  else pre.dataset.originalText = text;

  const regex = new RegExp(escRegExp(term), "gi");
  const matches = [...text.matchAll(regex)];
  if (!matches.length) {
    toast("未找到匹配内容", "info");
    return;
  }

  let current = parseInt(pre.dataset.findIndex || "-1");
  if (direction === "next") current = (current + 1) % matches.length;
  else current = (current - 1 + matches.length) % matches.length;
  pre.dataset.findIndex = String(current);

  let idx = -1;
  pre.innerHTML = esc(text).replace(regex, (match) => {
    idx++;
    const safe = esc(match);
    return idx === current
      ? `<span class="find-highlight">${safe}</span>`
      : `<span class="find-match">${safe}</span>`;
  });

  const highlight = pre.querySelector(".find-highlight");
  if (highlight) highlight.scrollIntoView({ block: "center", behavior: "smooth" });
}

function escRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\\\]/g, "\\$&");
}

// ── Config ──
async function loadConfig() {
  $("pageTitle").textContent = "API 配置";
  $("topbarActions").innerHTML = `<button class="btn btn-primary" id="importBtn">导入 JSON</button><button class="btn btn-primary" id="exportBtn">导出 JSON</button>`;
  $("content").innerHTML = '<div class="loading">加载中...</div>';
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
  let html = `<div class="section"><div class="section-header"><div class="section-title">全局配置</div><button class="btn btn-primary" id="saveGlobalBtn">保存全局配置</button></div>
    <div class="global-form">
      <div class="form-row">
        <div class="form-group"><label>全局超时时间（秒）</label><input type="number" id="globalTimeout" value="${globalConfig.global_default_timeout || 15}" min="1" max="120"/></div>
        <div class="form-group"><label>全局频率限制（次/分钟，0=不限）</label><input type="number" id="globalRateLimit" value="${globalConfig.global_rate_limit || 0}" min="0" max="9999"/></div>
        <div class="form-group"><label>请求失败重试次数（0=不重试）</label><input type="number" id="globalRetryCount" value="${globalConfig.global_retry_count || 0}" min="0" max="10"/></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>默认触发方式</label><select id="defaultTriggerType"><option value="direct" ${globalConfig.default_trigger_type==='direct'?'selected':''}>直接对话触发</option><option value="mention_only" ${globalConfig.default_trigger_type==='mention_only'?'selected':''}>仅@机器人触发</option></select></div>
      </div>
    </div>
  </div>`;

  for (const t of TYPE) {
    const items = allApis.filter(a => (a.__template_key || "text_type") === t.key);
    html += `<div class="section">
      <div class="section-header">
        <div class="section-title">${t.icon} ${t.label} <span class="count">（${items.length}）</span></div>
        <button class="btn btn-primary btn-sm add-api-btn" data-type="${t.key}">+ 新增</button>
      </div>`;
    if (!items.length) {
      html += `<div class="empty" style="padding:20px;">暂无配置</div>`;
    } else {
      html += `<div class="api-grid">`;
      for (let i = 0; i < allApis.length; i++) {
        const api = allApis[i];
        if ((api.__template_key || "text_type") !== t.key) continue;
        const urls = Array.isArray(api.api_url) ? api.api_url : [api.api_url].filter(Boolean);
        html += `<div class="api-card" data-idx="${i}">
          <div class="cmd">/${api.api_name || '-'}</div>
          <div class="meta-row"><span class="badge ${t.badge}">${t.label}</span><span class="meta-item"><span class="label">触发方式</span><span class="val">${TRIGGER[api.trigger_type] || "全局"}</span></span></div>
          <div class="meta-row"><span class="meta-item"><span class="label">请求</span><span class="val">${api.method || 'GET'}</span></span><span class="meta-item"><span class="label">超时</span><span class="val">${api.timeout ? api.timeout + 's' : '默认'}</span></span><span class="meta-item"><span class="label">频率</span><span class="val">${api.api_rate_limit ? api.api_rate_limit + '/min' : '全局'}</span></span></div>
          <div class="url-list">${urls.map(u => `<span class="url-tag" title="${esc(u)}">${esc(u)}</span>`).join('') || '<span style="font-size:0.75rem;color:var(--text-secondary)">未配置URL</span>'}</div>
          <div class="card-actions">
            <button class="btn btn-sm btn-muted edit-btn" data-idx="${i}">编辑</button>
            <button class="btn btn-sm btn-success test-btn" data-idx="${i}">测试</button>
            <button class="btn btn-sm btn-danger del-btn" data-idx="${i}">删除</button>
            <button class="btn btn-sm btn-info detail-btn" data-idx="${i}">详情</button>
          </div>
        </div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  $("content").innerHTML = html;

  document.getElementById("saveGlobalBtn")?.addEventListener("click", saveGlobal);
  document.getElementById("exportBtn")?.addEventListener("click", exportConfig);
  document.getElementById("importBtn")?.addEventListener("click", () => $("importFileInput").click());
  document.querySelectorAll(".add-api-btn").forEach(b => b.addEventListener("click", () => openAdd(b.dataset.type)));
  document.querySelectorAll(".edit-btn").forEach(b => b.addEventListener("click", () => openEdit(parseInt(b.dataset.idx))));
  document.querySelectorAll(".test-btn").forEach(b => b.addEventListener("click", () => openTestFromConfig(parseInt(b.dataset.idx))));
  document.querySelectorAll(".del-btn").forEach(b => b.addEventListener("click", () => deleteApi(parseInt(b.dataset.idx))));
  document.querySelectorAll(".detail-btn").forEach(b => b.addEventListener("click", () => showDetail(parseInt(b.dataset.idx))));
}

async function saveGlobal() {
  try {
    await bridge.apiPost("config/save-global", {
      global_default_timeout: parseInt($("globalTimeout").value) || 15,
      global_rate_limit: parseInt($("globalRateLimit").value) || 0,
      global_retry_count: parseInt($("globalRetryCount").value) || 0,
      default_trigger_type: $("defaultTriggerType").value,
    });
    toast("全局配置已保存");
  } catch (e) { toast("保存失败: " + (e.message || e), "error"); }
}

async function exportConfig() {
  try { await bridge.download("config/export", {}, "api_config.json"); toast("配置已导出"); }
  catch (e) { toast("导出失败: " + (e.message || e), "error"); }
}

$("importFileInput").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    await bridge.upload("config/import", file);
    toast("配置已导入");
    await loadConfig();
  } catch (err) { toast("导入失败: " + (err.message || err), "error"); }
  e.target.value = "";
});

function openTestFromConfig(idx) {
  testState.editIndex = idx;
  testState.config = idx >= 0 ? { ...allApis[idx] } : null;
  currentView = "test";
  navItems.forEach(n => n.classList.remove("active"));
  document.querySelector('.nav-item[data-view="test"]')?.classList.add("active");
  loadView("test");
}

// ── Edit/Add Modal ──
function openAdd(typeKey) {
  $("editIndex").value = "-1";
  $("editType").value = typeKey;
  $("editModalTitle").textContent = `新增 ${TYPE.find(t => t.key === typeKey)?.label || "API"}`;
  $("submitEditBtn").textContent = "创建";
  resetForm();
  openModal("editModal");
}
function openEdit(idx) {
  const api = allApis[idx];
  $("editIndex").value = idx;
  $("editType").value = api.__template_key || "text_type";
  $("editModalTitle").textContent = `编辑 /${api.api_name || ""}`;
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
function resetForm() {
  $("editApiName").value = "";
  $("editMethod").value = "GET";
  $("editTriggerType").value = "global";
  $("editApiUrl").value = "";
  $("editTimeout").value = "0";
  $("editRateLimit").value = "0";
  $("editDataPath").value = "";
  $("editParams").value = "";
  $("editHeaders").value = "";
  $("editBody").value = "";
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
    if (raw) {
      try { payload[f] = JSON.parse(raw); }
      catch (err) { toast(`${f} JSON 格式错误: ${err.message}`, "error"); $("submitEditBtn").disabled = false; return; }
    } else { payload[f] = {}; }
  }
  const editIdx = parseInt($("editIndex").value);
  try {
    if (editIdx >= 0) {
      await bridge.apiPost("config/update", { index: editIdx, config: payload });
      toast("API 已更新");
    } else {
      await bridge.apiPost("config/add", { config: payload });
      toast("API 已创建");
    }
    closeModal("editModal");
    await loadConfig();
  } catch (err) { toast("保存失败: " + (err.message || err), "error"); }
  finally { $("submitEditBtn").disabled = false; }
});

async function deleteApi(idx) {
  const api = allApis[idx];
  if (!confirm(`确定要删除 /${api?.api_name || "此API"} 吗？`)) return;
  try { await bridge.apiPost("config/delete", { index: idx }); toast("已删除"); await loadConfig(); }
  catch (e) { toast("删除失败: " + (e.message || e), "error"); }
}

// ── Detail Modal ──
function showDetail(idx) {
  const api = allApis[idx];
  const t = TYPE.find(t => t.key === (api.__template_key || "text_type"));
  const urls = Array.isArray(api.api_url) ? api.api_url.map(u => `<code>${esc(u)}</code>`).join("<br>") : (api.api_url || "-");
  const detailHtml = `
    <dl class="detail-grid">
      <dt>类型</dt><dd><span class="badge ${t?.badge || ""}">${t?.label || "-"}</span></dd>
      <dt>触发命令</dt><dd><strong>/${api.api_name || '-'}</strong></dd>
      <dt>请求方式</dt><dd>${api.method || "GET"}</dd>
      <dt>触发方式</dt><dd>${TRIGGER[api.trigger_type] || "全局"}</dd>
      <dt>超时</dt><dd>${api.timeout ? api.timeout + 's' : '默认'}</dd>
      <dt>频率限制</dt><dd>${api.api_rate_limit ? api.api_rate_limit + '/min' : '继承全局'}</dd>
      <dt>数据路径</dt><dd><code>${api.data_path || "(无)"}</code></dd>
      <dt>请求参数</dt><dd>${formatJson(api.params)}</dd>
      <dt>请求头</dt><dd>${formatJson(api.headers)}</dd>
      <dt>请求体</dt><dd>${formatJson(api.body)}</dd>
      <dt>API 地址</dt><dd>${urls}</dd>
    </dl>`;
  $("detailContent").innerHTML = detailHtml;
  openModal("detailModal");
}
function formatJson(obj) {
  if (!obj || !Object.keys(obj).length) return '<span style="color:var(--text-secondary)">(空)</span>';
  return `<pre>${esc(JSON.stringify(obj, null, 2))}</pre>`;
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
loadView(currentView);
