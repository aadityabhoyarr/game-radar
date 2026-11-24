// Game Radar Offline Dashboard Client

let allGames = [];
let sortCol = "display_score";
let sortAsc = false;
let subgenreData = [];
let logInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initFilters();
  loadGames();
  loadSubgenres();
  loadNiches();
  loadRuns();
  loadReports();

  document.getElementById("btnRunWorker").addEventListener("click", startWorker);
});

// Tab navigation
function initTabs() {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const target = document.getElementById(btn.getAttribute("data-tab"));
      if (target) target.classList.add("active");

      if (btn.getAttribute("data-tab") === "tab-runs") {
        startLogPolling();
      } else {
        stopLogPolling();
      }
    });
  });
}

// Filter events
function initFilters() {
  const minScoreInput = document.getElementById("filterMinScore");
  const minScoreVal = document.getElementById("minScoreVal");
  minScoreInput.addEventListener("input", (e) => {
    minScoreVal.textContent = e.target.value;
    loadGames();
  });

  const maxAgeInput = document.getElementById("filterMaxAge");
  const maxAgeVal = document.getElementById("maxAgeVal");
  maxAgeInput.addEventListener("input", (e) => {
    maxAgeVal.textContent = e.target.value;
    loadGames();
  });

  document.getElementById("filterGroup").addEventListener("change", loadGames);
  document.getElementById("filterCategory").addEventListener("change", loadGames);
  document.getElementById("filterSubgenre").addEventListener("change", loadGames);
  document.getElementById("filterConfidence").addEventListener("change", loadGames);
  document.getElementById("filterSearch").addEventListener("input", debounce(loadGames, 300));

  document.getElementById("hideBig").addEventListener("change", loadGames);
  document.getElementById("hideHyper").addEventListener("change", loadGames);
  document.getElementById("hideFranchise").addEventListener("change", loadGames);
  document.getElementById("hidePaid").addEventListener("change", loadGames);

  document.getElementById("sgGroupSelect").addEventListener("change", renderSubgenres);

  // Table header sorting
  document.querySelectorAll("#radarTable th[data-col]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.getAttribute("data-col");
      if (sortCol === col) {
        sortAsc = !sortAsc;
      } else {
        sortCol = col;
        sortAsc = false;
      }
      renderRadarTable();
    });
  });
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

// Load Games via API
async function loadGames() {
  const group = document.getElementById("filterGroup").value;
  const category = document.getElementById("filterCategory").value;
  const subgenre = document.getElementById("filterSubgenre").value;
  const min_score = document.getElementById("filterMinScore").value;
  const max_age = document.getElementById("filterMaxAge").value;
  const confidence = document.getElementById("filterConfidence").value;
  const hide_big = document.getElementById("hideBig").checked;
  const hide_hyper = document.getElementById("hideHyper").checked;
  const hide_franchise = document.getElementById("hideFranchise").checked;
  const hide_paid = document.getElementById("hidePaid").checked;
  const search = document.getElementById("filterSearch").value;

  const params = new URLSearchParams({
    group,
    min_score,
    max_age,
    hide_big,
    hide_hyper,
    hide_franchise,
    hide_paid
  });
  if (category) params.append("category", category);
  if (subgenre) params.append("subgenre", subgenre);
  if (confidence) params.append("confidence", confidence);
  if (search) params.append("search", search);

  try {
    const res = await fetch(`/api/games?${params.toString()}`);
    const data = await res.json();
    allGames = data.games || [];
    populateCategoriesAndTags(allGames);
    renderRadarTable();
  } catch (err) {
    console.error("Failed to load games:", err);
  }
}

function populateCategoriesAndTags(games) {
  const catSel = document.getElementById("filterCategory");
  const subSel = document.getElementById("filterSubgenre");
  if (catSel.options.length <= 1) {
    const cats = new Set();
    const tags = new Set();
    games.forEach(g => {
      if (g.category) cats.add(g.category);
      (g.tags || []).forEach(t => tags.add(t));
    });
    Array.from(cats).sort().forEach(c => {
      const opt = document.createElement("option");
      opt.value = c; opt.textContent = c;
      catSel.appendChild(opt);
    });
    Array.from(tags).sort().forEach(t => {
      const opt = document.createElement("option");
      opt.value = t; opt.textContent = t;
      subSel.appendChild(opt);
    });
  }
}

function renderRadarTable() {
  const tbody = document.getElementById("radarTableBody");
  if (!allGames.length) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--text-muted)">No games matched the current filters.</td></tr>`;
    return;
  }

  // Sort
  allGames.sort((a, b) => {
    let valA = a[sortCol];
    let valB = b[sortCol];
    if (valA === null || valA === undefined) valA = -999999;
    if (valB === null || valB === undefined) valB = -999999;
    if (typeof valA === "string") valA = valA.toLowerCase();
    if (typeof valB === "string") valB = valB.toLowerCase();
    if (valA < valB) return sortAsc ? -1 : 1;
    if (valA > valB) return sortAsc ? 1 : -1;
    return 0;
  });

  tbody.innerHTML = allGames.map(g => {
    const tagsStr = (g.tags || []).slice(0, 3).join(", ");
    const flags = g.flags || {};
    let flagBadges = "";
    if (flags.big_publisher) flagBadges += `<span class="badge badge-big">Big</span> `;
    if (flags.hypercasual_publisher) flagBadges += `<span class="badge badge-hyper">Hyper</span> `;
    if (flags.franchise) flagBadges += `<span class="badge badge-big">Franchise</span> `;
    if (flags.paid_traffic_suspect) flagBadges += `<span class="badge badge-paid">Paid</span> `;
    if (!flags.hidden_by_default && !flags.paid_traffic_suspect) flagBadges += `<span class="badge badge-clean">Clean</span>`;

    const confClass = g.confidence === "HIGH" ? "badge-conf-high" : (g.confidence === "MEDIUM" ? "badge-conf-med" : "badge-conf-low");

    return `
      <tr>
        <td><b style="font-size:15px; color:var(--accent)">${(g.display_score || 0).toFixed(1)}</b></td>
        <td>
          <div style="font-weight:600; color:#fff">${escapeHtml(g.title || g.app_id)}</div>
          <div style="font-size:11px; color:var(--text-muted)"><code>${g.app_id}</code></div>
        </td>
        <td>${escapeHtml(g.developer || "")}</td>
        <td>
          <div>${escapeHtml(g.category || "")}</div>
          <div style="font-size:11px; color:var(--text-muted)">${escapeHtml(tagsStr)}</div>
        </td>
        <td>${g.age_days || "?"}d</td>
        <td>${formatNum(g.real_installs)}</td>
        <td>${formatNum(g.v7)}</td>
        <td><span class="badge ${confClass}">${g.confidence || "LOW"}</span></td>
        <td>${flagBadges}</td>
        <td>
          <button class="btn btn-secondary" style="padding:4px 8px; font-size:11px" onclick="openGameModal('${g.app_id}')">Inspect</button>
        </td>
      </tr>
    `;
  }).join("");
}

// Subgenres
async function loadSubgenres() {
  try {
    const res = await fetch("/api/subgenres");
    const data = await res.json();
    subgenreData = data.subgenres || [];
    renderSubgenres();
  } catch (err) {
    console.error("Failed to load subgenres:", err);
  }
}

function renderSubgenres() {
  const grp = document.getElementById("sgGroupSelect").value;
  const tbody = document.getElementById("subgenreTableBody");
  const filtered = subgenreData.filter(s => s.group_name === grp);

  tbody.innerHTML = filtered.slice(0, 15).map((s, idx) => {
    const ev = (s.evidence_games || []).map(e => `
      <a href="#" onclick="openGameModal('${e.app_id}'); return false;" style="font-size:11px;">
        ${escapeHtml(e.title || e.app_id)} (${(e.trend_score||0).toFixed(0)})
      </a>
    `).join(" &bull; ");

    return `
      <tr>
        <td>#${idx + 1}</td>
        <td><b>${escapeHtml(s.tag)}</b></td>
        <td><b style="color:var(--green); font-size:15px;">${(s.build_now_score||0).toFixed(1)}</b></td>
        <td>${(s.comp_momentum||0).toFixed(1)}</td>
        <td>${(s.comp_breadth||0).toFixed(1)}</td>
        <td>${(s.comp_openness||0).toFixed(1)}</td>
        <td>${(s.comp_demand||0).toFixed(1)} ${s.demand_missing ? '<small style="color:var(--amber)">(adj)</small>' : ''}</td>
        <td>${(s.comp_monetization||0).toFixed(1)}</td>
        <td>${ev || "None"}</td>
      </tr>
    `;
  }).join("");
}

// Niches & Keywords
async function loadNiches() {
  try {
    const res = await fetch("/api/niches");
    const data = await res.json();

    const kwBody = document.getElementById("keywordsTableBody");
    kwBody.innerHTML = (data.keywords || []).map(k => `
      <tr>
        <td><b>${escapeHtml(k.keyword)}</b></td>
        <td>${k.prefix_len}</td>
        <td><b style="color:var(--accent)">${(k.opportunity_score||0).toFixed(1)}</b></td>
        <td>${formatNum(k.median_installs)}</td>
        <td>${((k.brand_share||0)*100).toFixed(0)}%</td>
        <td>${k.exact_match_titles||0}</td>
        <td>${k.cohort_in_top10 ? '<span class="badge badge-clean">Yes</span>' : '<span style="color:var(--text-muted)">No</span>'}</td>
      </tr>
    `).join("");

    const trBody = document.getElementById("trendsTableBody");
    trBody.innerHTML = (data.trends || []).map(t => `
      <tr>
        <td><b>${escapeHtml(t.keyword)}</b></td>
        <td>${t.region}</td>
        <td>${t.latest_value}</td>
        <td style="color:${t.slope_12w > 0 ? 'var(--green)' : 'var(--red)'}"><b>${t.slope_12w}</b></td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Failed to load niches:", err);
  }
}

// Runs & Worker
async function loadRuns() {
  try {
    const res = await fetch("/api/runs");
    const data = await res.json();
    const tbody = document.getElementById("runsTableBody");
    tbody.innerHTML = (data.runs || []).map(r => `
      <tr>
        <td><code>${r.run_id}</code></td>
        <td>${r.mode}</td>
        <td><span class="badge ${r.status==='COMPLETED'?'badge-clean':'badge-paid'}">${r.status}</span></td>
        <td>${r.start_time}</td>
        <td>${r.end_time || "Running"}</td>
        <td>${r.total_requests}</td>
        <td>${r.total_failures}</td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Failed to load runs:", err);
  }
}

async function startWorker() {
  const mode = document.getElementById("workerMode").value;
  try {
    const res = await fetch(`/api/runs/start?mode=${mode}`, { method: "POST" });
    const data = await res.json();
    alert(`Worker run initiated in ${mode} mode.`);
    startLogPolling();
  } catch (err) {
    alert(`Failed to start worker: ${err}`);
  }
}

function startLogPolling() {
  stopLogPolling();
  fetchLogs();
  logInterval = setInterval(fetchLogs, 2000);
}

function stopLogPolling() {
  if (logInterval) {
    clearInterval(logInterval);
    logInterval = null;
  }
}

async function fetchLogs() {
  try {
    const res = await fetch("/api/runs/logs/live");
    const data = await res.json();
    const box = document.getElementById("liveLogBox");
    if (data.lines && data.lines.length) {
      box.textContent = data.lines.join("");
      box.scrollTop = box.scrollHeight;
    }
  } catch (err) {
    console.error("Log fetch error:", err);
  }
}

// Reports
async function loadReports() {
  try {
    const res = await fetch("/api/reports");
    const data = await res.json();
    const tbody = document.getElementById("reportsTableBody");
    tbody.innerHTML = (data.reports || []).map(rp => `
      <tr>
        <td><b>${escapeHtml(rp.name)}</b></td>
        <td>${rp.size_kb} KB</td>
        <td>${rp.modified}</td>
        <td>
          <a href="/api/reports/view/${rp.name}" target="_blank" class="btn btn-secondary" style="padding:4px 8px; font-size:11px;">Open / View</a>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Failed to load reports:", err);
  }
}

// Modal Detail View
async function openGameModal(appId) {
  const modal = document.getElementById("gameModal");
  const content = document.getElementById("gameModalContent");
  modal.style.display = "block";
  content.innerHTML = `<div style="text-align:center; padding:40px;">Loading details for ${appId}...</div>`;

  try {
    const res = await fetch(`/api/game/${appId}`);
    const data = await res.json();
    renderGameModalContent(data);
  } catch (err) {
    content.innerHTML = `<div style="color:var(--red); padding:20px;">Failed to load game: ${err}</div>`;
  }
}

function closeGameModal() {
  document.getElementById("gameModal").style.display = "none";
}

function renderGameModalContent(d) {
  const app = d.app || {};
  const metric = d.metric || {};
  const links = d.links || {};
  const why = JSON.parse(metric.why_growing || "{}");
  const drivers = why.drivers || [];
  const flags = JSON.parse(metric.brand_flags || "{}");

  const content = document.getElementById("gameModalContent");
  content.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px;">
      <div style="display:flex; gap:16px; align-items:center;">
        <img src="${app.icon || ''}" style="width:64px; height:64px; border-radius:12px; background:#000;" onerror="this.style.display='none'">
        <div>
          <h2 style="font-size:22px; color:#fff; margin-bottom:4px;">${escapeHtml(app.title || app.app_id)}</h2>
          <div style="color:var(--text-muted); font-size:13px;">${escapeHtml(app.developer || '')} &bull; <code>${app.app_id}</code></div>
          <div style="color:var(--text-muted); font-size:12px; margin-top:2px;">Released: ${app.released || 'Unknown'} (Age: ${metric.age_days || '?'}d)</div>
        </div>
      </div>
      <div>
        <div style="text-align:right">
          <div style="font-size:11px; color:var(--text-muted)">TREND SCORE</div>
          <div style="font-size:32px; font-weight:800; color:var(--accent)">${(metric.trend_score_all || 0).toFixed(1)}</div>
        </div>
      </div>
    </div>

    <!-- Action Links -->
    <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:20px;">
      <a href="${links.play_store}" target="_blank" class="btn btn-secondary">Google Play</a>
      <a href="${links.meta_ad_library}" target="_blank" class="btn btn-secondary">Meta Ad Library</a>
      <a href="${links.androidrank}" target="_blank" class="btn btn-secondary">AndroidRank</a>
      <button class="btn btn-primary" onclick="navigator.clipboard.writeText('${escapeHtml(app.title || '')}'); alert('Copied game name!');">Copy Name</button>
      <a href="${links.appmagic}" target="_blank" class="btn btn-secondary">AppMagic.rocks</a>
    </div>

    <!-- Score Breakdown -->
    <div class="card" style="margin-bottom:16px;">
      <h3 style="font-size:14px; margin-bottom:10px;">Score Components</h3>
      <div style="display:grid; grid-template-columns: repeat(5, 1fr); gap:10px; text-align:center;">
        <div style="background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
          <div style="font-size:11px; color:var(--text-muted)">V7 Speed (40)</div>
          <div style="font-weight:700; font-size:16px;">${(metric.comp_v7 || 0).toFixed(1)}</div>
        </div>
        <div style="background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
          <div style="font-size:11px; color:var(--text-muted)">Acceleration (15)</div>
          <div style="font-weight:700; font-size:16px;">${(metric.comp_acc || 0).toFixed(1)}</div>
        </div>
        <div style="background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
          <div style="font-size:11px; color:var(--text-muted)">Freshness (15)</div>
          <div style="font-weight:700; font-size:16px;">${(metric.comp_freshness || 0).toFixed(1)}</div>
        </div>
        <div style="background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
          <div style="font-size:11px; color:var(--text-muted)">Coverage (20)</div>
          <div style="font-weight:700; font-size:16px;">${(metric.comp_coverage || 0).toFixed(1)}</div>
        </div>
        <div style="background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
          <div style="font-size:11px; color:var(--text-muted)">Rating (10)</div>
          <div style="font-weight:700; font-size:16px;">${(metric.comp_rating || 0).toFixed(1)}</div>
        </div>
      </div>
    </div>

    <!-- Why Growing -->
    <div class="card" style="margin-bottom:16px;">
      <h3 style="font-size:14px; margin-bottom:8px;">Growth Drivers (ESTIMATE)</h3>
      ${drivers.length ? drivers.map(dr => `
        <div style="font-size:13px; margin-bottom:4px;">
          &bull; <b>[${dr.label}] ${dr.driver}:</b> <span style="color:var(--text-muted)">${escapeHtml(dr.evidence)}</span>
        </div>
      `).join('') : '<div style="color:var(--text-muted); font-size:12px;">Standard organic chart discovery.</div>'}
      <div style="font-size:12px; color:var(--text-muted); margin-top:8px;"><b>How Found:</b> ${escapeHtml(why.how_found || metric.how_found || 'Store scan')}</div>
    </div>

    <!-- Charts -->
    <div class="card" style="margin-bottom:16px;">
      <h3 style="font-size:14px; margin-bottom:6px;">Daily Review Activity (Last 90 Days)</h3>
      <div class="chart-container" id="reviewChartContainer">
        <canvas id="reviewCanvas" style="width:100%; height:100%"></canvas>
      </div>

      <h3 style="font-size:14px; margin-bottom:6px;">Install Snapshot History & Counter Steps</h3>
      <div class="chart-container" id="installChartContainer">
        <canvas id="installCanvas" style="width:100%; height:100%"></canvas>
      </div>
    </div>

    <!-- Manual Fields & Notes -->
    <div class="card">
      <h3 style="font-size:14px; margin-bottom:10px;">Manual Intelligence (AppMagic & Notes)</h3>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:12px;">
        <div>
          <label style="font-size:11px; color:var(--text-muted)">AppMagic Monthly Revenue ($)</label>
          <input type="number" id="appmagicRev" class="form-control" value="${app.appmagic_revenue_monthly || ''}" placeholder="e.g. 25000">
        </div>
        <div>
          <label style="font-size:11px; color:var(--text-muted)">AppMagic Monthly Downloads</label>
          <input type="number" id="appmagicDl" class="form-control" value="${app.appmagic_downloads_monthly || ''}" placeholder="e.g. 500000">
        </div>
      </div>
      <div>
        <label style="font-size:11px; color:var(--text-muted)">Analyst Notes</label>
        <textarea id="appNotes" class="form-control" rows="3" placeholder="Enter notes about game mechanics, ads, publisher...">${escapeHtml(app.notes || '')}</textarea>
      </div>
      <button class="btn btn-success" style="margin-top:10px;" onclick="saveManualFields('${app.app_id}')">Save Changes</button>
    </div>
  `;

  // Draw Canvas charts
  drawReviewsCanvas(d.reviews || []);
  drawInstallsCanvas(d.snapshots || []);
}

function drawReviewsCanvas(reviews) {
  const canvas = document.getElementById("reviewCanvas");
  if (!canvas || !reviews.length) return;
  canvas.width = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;
  const ctx = canvas.getContext("2d");

  const counts = reviews.map(r => r.cnt || 0);
  const maxVal = Math.max(...counts, 1);
  const w = canvas.width;
  const h = canvas.height;
  const padding = 20;

  ctx.strokeStyle = "#38bdf8";
  ctx.fillStyle = "rgba(56, 189, 248, 0.2)";
  ctx.lineWidth = 2;

  ctx.beginPath();
  const step = (w - padding * 2) / Math.max(1, reviews.length - 1);
  reviews.forEach((r, idx) => {
    const x = padding + idx * step;
    const y = h - padding - ((r.cnt || 0) / maxVal) * (h - padding * 2);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Draw points
  ctx.fillStyle = "#38bdf8";
  reviews.forEach((r, idx) => {
    const x = padding + idx * step;
    const y = h - padding - ((r.cnt || 0) / maxVal) * (h - padding * 2);
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function drawInstallsCanvas(snapshots) {
  const canvas = document.getElementById("installCanvas");
  if (!canvas || !snapshots.length) return;
  canvas.width = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;
  const ctx = canvas.getContext("2d");

  const vals = snapshots.map(s => s.real_installs || 0);
  const maxVal = Math.max(...vals, 1);
  const w = canvas.width;
  const h = canvas.height;
  const padding = 20;

  ctx.strokeStyle = "#4ade80";
  ctx.lineWidth = 2;

  ctx.beginPath();
  const step = (w - padding * 2) / Math.max(1, snapshots.length - 1);
  snapshots.forEach((s, idx) => {
    const x = padding + idx * step;
    const y = h - padding - ((s.real_installs || 0) / maxVal) * (h - padding * 2);
    if (idx === 0) ctx.moveTo(x, y);
    else {
      // Dotted line if value didn't change
      if (s.real_installs === snapshots[idx - 1].real_installs) {
        ctx.setLineDash([4, 4]);
      } else {
        ctx.setLineDash([]);
      }
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
  ctx.setLineDash([]);
}

async function saveManualFields(appId) {
  const rev = parseFloat(document.getElementById("appmagicRev").value) || null;
  const dl = parseFloat(document.getElementById("appmagicDl").value) || null;
  const notes = document.getElementById("appNotes").value;

  try {
    const res = await fetch(`/api/game/${appId}/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        appmagic_revenue_monthly: rev,
        appmagic_downloads_monthly: dl,
        notes: notes
      })
    });
    if (res.ok) {
      alert("Manual details saved to database.");
    }
  } catch (err) {
    alert("Save failed: " + err);
  }
}

function formatNum(n) {
  if (n === null || n === undefined) return "0";
  return Number(n).toLocaleString();
}

function escapeHtml(s) {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
