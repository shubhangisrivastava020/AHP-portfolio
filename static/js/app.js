// ─────────────────────────────────────────────────────────────
// AI-AHP Pension Fund Portfolio Allocation System  v4.0
// Frontend Application Logic
// ─────────────────────────────────────────────────────────────

const COLORS = [
  '#2563eb','#10b981','#f59e0b','#ef4444',
  '#8b5cf6','#06b6d4','#f97316'
];

const FUND_COLORS = [
  '#2563eb','#10b981','#f59e0b','#ef4444',
  '#8b5cf6','#06b6d4','#f97316','#ec4899'
];

let state = {
  result:       null,
  mc:           null,
  evidence:     null,
  constants:    null,
  benchmarkData: null,
  chatHistory:  [],
};

let charts = {};

// ── INIT ─────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  try {
    const r = await fetch('/api/constants');
    state.constants = await r.json();
  } catch(e) { console.warn('Could not load constants', e); }
  loadEvidence();
});

// ── AUTO-RERUN ON CONFIG CHANGE ───────────────────────────────
let _runTimer = null;
function debouncedRun() {
  if (!state.result) return;
  const upd = document.getElementById('allocUpdating');
  const crUpd = document.getElementById('crUpdating');
  if (upd) upd.style.display = 'inline';
  if (crUpd) crUpd.style.display = 'inline';
  clearTimeout(_runTimer);
  _runTimer = setTimeout(async () => {
    await runModel();
    if (upd) upd.style.display = 'none';
    if (crUpd) crUpd.style.display = 'none';
  }, 800);
}

// ── TAB NAVIGATION ────────────────────────────────────────────
function showTab(name) {
  // Redirect removed tabs to dashboard
  if (name === 'matrices' || name === 'montecarlo' || name === 'acadian') {
    showTab('dashboard');
    return;
  }
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  const panel = document.getElementById('tab-' + name);
  if (!panel) return;
  panel.classList.add('active');
  [...document.querySelectorAll('.nav-tab')]
    .find(t => t.getAttribute('onclick')?.includes("'" + name + "'"))
    ?.classList.add('active');
  if (name === 'hierarchy') { renderHierarchy(); renderSubCritCards('return'); }
}

// ── SECTION COLLAPSE TOGGLE ───────────────────────────────────
function toggleSection(id, header) {
  const el = document.getElementById(id);
  if (!el) return;
  const isOpen = el.style.display !== 'none';
  el.style.display = isOpen ? 'none' : 'block';
  const arrow = header.querySelector('span:first-child');
  if (arrow) arrow.textContent = (isOpen ? '▶' : '▼') + arrow.textContent.slice(1);
}

// ── TOAST ─────────────────────────────────────────────────────
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show ' + type;
  setTimeout(() => { el.className = ''; }, 3500);
}

// ── RUN MODEL ─────────────────────────────────────────────────
async function runModel() {
  const btn  = document.getElementById('runBtn');
  const text = document.getElementById('runBtnText');
  btn.disabled = true;
  text.innerHTML = '<span class="spinner"></span>';

  const payload = {
    fund_name:     document.getElementById('cfgFund')?.value || 'Liberty Bell Pension Fund',
    aum:           parseFloat(document.getElementById('cfgAum')?.value || '3.2'),
    scenario:      document.getElementById('cfgScenario')?.value || 'Steady Growth',
    n_simulations: 1000,
  };

  try {
    const r    = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (data.status !== 'ok') throw new Error(data.error || 'Unknown error');

    state.result = data.result;
    state.mc     = data.monte_carlo;

    renderDashboard(data);
    renderMonteCarlo(data);
    renderMatrices(data);

    const heroGrade = document.getElementById('heroGrade');
    const heroAum   = document.getElementById('heroAum');
    if (heroGrade) heroGrade.textContent = data.result.overall_grade;
    if (heroAum)   heroAum.textContent   = '$' + payload.aum + 'B';
    updateChatContextStatus();

    toast('Model run complete — Grade ' + data.result.overall_grade);
  } catch(e) {
    toast('Error: ' + e.message, 'error');
    console.error(e);
  } finally {
    btn.disabled = false;
    text.innerHTML = '▶ Run Model';
  }
}

// ── DASHBOARD ─────────────────────────────────────────────────
function renderDashboard(data) {
  const { result, monte_carlo: mc, asset_classes } = data;
  const w  = result.constrained_weights;
  const cr = result.consistency_results;

  document.getElementById('dashEmpty').style.display   = 'none';
  document.getElementById('dashResults').style.display = 'block';

  const top    = Object.entries(w).sort((a,b) => b[1]-a[1])[0];
  const allCRs = Object.values(cr).map(c => c.CR);
  const avgCR  = (allCRs.reduce((s,v) => s+v, 0) / allCRs.length).toFixed(4);
  const highSens = mc ? Object.entries(mc).filter(([,v]) => v.sensitivity==='HIGH').map(([k]) => k) : [];

  document.getElementById('kpiRow').innerHTML = [
    { label:'Overall Grade',     value: result.overall_grade, sub:'All 10 matrices', color: gradeColor(result.overall_grade) },
    { label:'Top Allocation',    value: top[0].split(' ')[0], sub: pct(top[1]), color:'#2563eb' },
    { label:'Avg CR',            value: avgCR, sub: allCRs.filter(c=>c<=0.10).length + '/10 pass', color:'#10b981' },
    { label:'High Sensitivity',  value: highSens.length || '0', sub: highSens.join(', ') || 'All stable', color: highSens.length ? '#ef4444' : '#10b981' },
  ].map(k => `
    <div class="stat-card">
      <div class="stat-label">${k.label}</div>
      <div class="stat-value" style="color:${k.color}">${k.value}</div>
      <div class="stat-sub">${k.sub}</div>
    </div>`).join('');

  const maxW = Math.max(...Object.values(w));
  document.getElementById('allocBars').innerHTML = asset_classes.map((a, i) => `
    <div class="alloc-row">
      <div class="alloc-label">${a}</div>
      <div class="alloc-bar-wrap">
        <div class="alloc-bar" style="width:${(w[a]/maxW*100).toFixed(1)}%;background:${COLORS[i]}"></div>
      </div>
      <div class="alloc-pct">${pct(w[a])}</div>
      <div class="alloc-usd">$${result.dollar_allocation[a].toFixed(3)}B</div>
    </div>`).join('');

  if (charts.donut) { charts.donut.destroy(); charts.donut = null; }

  document.getElementById('crList').innerHTML = Object.entries(cr).map(([name, v]) => `
    <div class="cr-row">
      <span class="cr-name">${name.replace('_',' ')}</span>
      <span style="display:flex;align-items:center;gap:8px">
        <span class="cr-value">CR = ${v.CR.toFixed(4)}</span>
        <span class="grade grade-${v.grade}">${v.grade}</span>
        ${v.repair_iters > 0 ? `<span class="pill">${v.repair_iters} repairs</span>` : ''}
      </span>
    </div>`).join('');

  const rr = result.rank_reversal_flag;
  document.getElementById('dualSynthResult').innerHTML = `
    <span class="pill ${rr ? 'red' : 'green'}">
      ${rr ? '⚠ Rank reversal flagged' : '✓ Dual synthesis stable'}
    </span>
    <div style="font-size:.78rem;color:var(--muted);margin-top:6px">${result.rank_reversal_msg}</div>`;

  if (charts.criteria) { charts.criteria.destroy(); charts.criteria = null; }

  // Update decision breakdown (AI Advisor tab)
  updateDecisionBreakdown(result, state.evidence);
  // Refresh sub-criteria cards with live evidence if hierarchy tab is visible
  const activeSubTab = document.querySelector('.subcrit-tab.active');
  if (activeSubTab) {
    const group = activeSubTab.textContent.includes('Risk') ? 'risk' : 'return';
    renderSubCritCards(group);
  } else {
    renderSubCritCards('return');
  }

  // Update hierarchy active config panel
  const topAssetEl = document.getElementById('cfgActiveTopAsset');
  if (topAssetEl) topAssetEl.textContent = top[0] + ' (' + pct(top[1]) + ')';
  const scenarioEl = document.getElementById('cfgActiveScenario');
  if (scenarioEl) scenarioEl.textContent = document.getElementById('cfgScenario')?.value || 'Steady Growth';
  const horizonEl = document.getElementById('cfgActiveHorizon');
  if (horizonEl) horizonEl.textContent = document.getElementById('cfgHorizon')?.value || 'Long-term';
  const riskEl = document.getElementById('cfgActiveRisk');
  if (riskEl) riskEl.textContent = document.getElementById('cfgRisk')?.value || 'Moderate';
  const criterionEl = document.getElementById('cfgActiveCriterion');
  if (criterionEl && result.criteria_weights) {
    const topCrit = Object.entries(result.criteria_weights).sort((a,b) => b[1]-a[1])[0];
    criterionEl.textContent = topCrit ? topCrit[0] + ' (' + pct(topCrit[1]) + ')' : '—';
  }
}

// ── MONTE CARLO ───────────────────────────────────────────────
function renderMonteCarlo(data) {
  const mc = data.monte_carlo;
  const assets = data.asset_classes;

  const mcEmpty = document.getElementById('mcEmpty');
  if (mcEmpty) mcEmpty.style.display = 'none';
  document.getElementById('mcContent').style.display = 'block';

  document.getElementById('mcTable').innerHTML = assets.map((a, i) => {
    const d = mc[a];
    return `<tr>
      <td>${a}</td>
      <td>${pct(d.mean)}</td>
      <td>${pct(d.std)}</td>
      <td>${pct(d.P5)}</td>
      <td>${pct(d.P95)}</td>
      <td><span class="sens-${d.sensitivity}">${d.sensitivity}</span></td>
    </tr>`;
  }).join('');

  if (charts.mc) charts.mc.destroy();
  charts.mc = new Chart(document.getElementById('mcChart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: assets,
      datasets: [
        { label: 'P5',   data: assets.map(a => +(mc[a].P5*100).toFixed(2)), backgroundColor: 'rgba(239,68,68,.25)', borderColor: '#ef4444', borderWidth:1 },
        { label: 'Mean', data: assets.map(a => +(mc[a].mean*100).toFixed(2)), backgroundColor: COLORS, borderRadius: 4 },
        { label: 'P95',  data: assets.map(a => +(mc[a].P95*100).toFixed(2)), backgroundColor: 'rgba(16,185,129,.25)', borderColor: '#10b981', borderWidth:1 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend:{ labels:{ color:'#e2e8f0' } } },
      scales: {
        x: { ticks:{ color:'#64748b', font:{size:10} }, grid:{ color:'#1e2d45' } },
        y: { ticks:{ color:'#64748b', callback: v => v+'%' }, grid:{ color:'#1e2d45' } },
      },
    },
  });
}

// ── MATRICES ─────────────────────────────────────────────────
function renderMatrices(data) {
  document.getElementById('matricesEmpty').style.display   = 'none';
  document.getElementById('matricesContent').style.display = 'block';
  window._matrixData = data;
  const sel = document.getElementById('matrixSelector');
  sel.innerHTML = Object.keys(data.result.consistency_results).map(k => `<option value="${k}">${k.replace('_',' ')}</option>`).join('');
  renderMatrix();
}

function renderMatrix() {
  const data = window._matrixData;
  if (!data) return;
  const key  = document.getElementById('matrixSelector').value;
  const cr   = data.result.consistency_results[key];
  if (!cr) return;

  document.getElementById('matrixStats').innerHTML = `
    <div class="cr-row"><span>Consistency Ratio (CR)</span><span class="cr-value">${cr.CR.toFixed(4)}</span></div>
    <div class="cr-row"><span>Consistency Index (CI)</span><span class="cr-value">${cr.CI.toFixed(4)}</span></div>
    <div class="cr-row"><span>Lambda Max</span><span class="cr-value">${cr.lambda_max.toFixed(4)}</span></div>
    <div class="cr-row"><span>Grade</span><span class="grade grade-${cr.grade}">${cr.grade}</span></div>
    <div class="cr-row"><span>Auto-Repairs</span><span class="cr-value">${cr.repair_iters}</span></div>
    <div style="margin-top:14px;font-size:.8rem;color:var(--muted)">
      ${cr.CR <= 0.10
        ? '<span class="pill green">✓ CR ≤ 0.10 — Acceptable consistency</span>'
        : '<span class="pill red">⚠ CR > 0.10 — Review required</span>'}
    </div>`;

  const LABELS = {
    Actors: ['Sponsor','Beneficiaries','Portfolio Mgr'],
    Horizon: ['Short-term','Medium-term','Long-term'],
    Scenarios: ['Bull Market','Stagflation','Deflation','Steady Growth'],
    Criteria: ['Return','Risk','Liquidity','Diversification'],
    Risk_Sub: ['Beta','Volatility','Max Drawdown','Liquidity Risk'],
    Return_Sub: ['Exp Return','Dividend Yield','Growth Potential'],
  };
  const assetClasses = ['Small Stocks','Large Stocks','Corp Bonds','Govt Bonds','Real Estate','Money Market','Commodities'];
  const labels = LABELS[key] || assetClasses;

  let head = '<thead><tr><th></th>' + labels.map(l => `<th>${l.split(' ')[0]}</th>`).join('') + '</tr></thead>';
  let body = '<tbody>' + labels.map((r, i) =>
    `<tr><td style="font-weight:600;color:var(--muted)">${r.split(' ')[0]}</td>` +
    labels.map((c, j) => {
      if (i === j) return '<td style="color:var(--muted)">1.000</td>';
      return `<td style="color:var(--text)">—</td>`;
    }).join('') + '</tr>'
  ).join('') + '</tbody>';

  document.getElementById('matrixTable').innerHTML = head + body;
}

// ── EVIDENCE ─────────────────────────────────────────────────
async function loadEvidence() {
  const scenario = document.getElementById('evScenario')?.value || 'Steady Growth';
  try {
    const r    = await fetch('/api/evidence?scenario=' + encodeURIComponent(scenario));
    const data = await r.json();
    state.evidence = data;

    // Render live data status banner
    const meta   = data.data_meta || {};
    const banner = document.getElementById('liveDataBanner');
    const badge  = document.getElementById('liveDataBadge');
    const src    = document.getElementById('liveDataSource');
    const win    = document.getElementById('liveDataWindow');
    const ts     = document.getElementById('liveDataTime');
    if (banner) {
      banner.style.display = 'flex';
      if (meta.live && !meta.from_cache) {
        banner.style.background = 'rgba(0,210,130,.12)';
        banner.style.border     = '1px solid rgba(0,210,130,.3)';
        badge.textContent       = 'LIVE';
        badge.style.background  = '#00d282';
        badge.style.color       = '#0a0f1e';
      } else if (meta.from_cache) {
        banner.style.background = 'rgba(250,190,0,.10)';
        banner.style.border     = '1px solid rgba(250,190,0,.3)';
        badge.textContent       = 'CACHED';
        badge.style.background  = '#fabc00';
        badge.style.color       = '#0a0f1e';
      } else {
        banner.style.background = 'rgba(120,120,150,.12)';
        banner.style.border     = '1px solid rgba(120,120,150,.25)';
        badge.textContent       = 'FALLBACK';
        badge.style.background  = '#8888aa';
        badge.style.color       = '#fff';
      }
      const proxyNames = meta.proxy_names || meta.proxies || {};
      const proxyList  = Object.values(proxyNames).join(', ') || 'IWM, SPY, LQD, IEF, VNQ, BIL, GSG';
      src.textContent  = (meta.source || 'Research-calibrated estimates') + (proxyList ? ' · ' + proxyList : '');
      win.textContent  = meta.data_window ? ('· ' + meta.data_window) : '';
      ts.textContent   = meta.fetched_at ? ('Data as of: ' + meta.fetched_at) : '';
    }

    document.getElementById('evBody').innerHTML = data.asset_classes.map(a => {
      const d      = data.evidence[a];
      const ticker = (meta.proxies || {})[a] || '';
      return `<tr>
        <td style="font-weight:600">${a}</td>
        <td style="font-size:.8rem;color:var(--accent2);font-weight:600">${ticker || '—'}</td>
        <td>${d.expected_return.toFixed(1)}</td>
        <td>${d.beta.toFixed(2)}</td>
        <td>${d.volatility.toFixed(1)}</td>
        <td style="color:var(--red)">${d.max_drawdown.toFixed(1)}</td>
        <td><div class="progress-wrap" style="width:80px"><div class="progress-bar" style="width:${d.liquidity*10}%"></div></div></td>
        <td>${d.avg_correlation.toFixed(2)}</td>
        <td style="color:${d.sharpe < 0 ? 'var(--red)' : 'inherit'}">${d.sharpe < 0 ? 'N/A' : d.sharpe.toFixed(2)}</td>
      </tr>`;
    }).join('');

    renderCorrelation(data);
  } catch(e) { console.error('Evidence load failed', e); }
}

async function refreshLiveData() {
  const btn = document.getElementById('btnRefreshLive');
  if (btn) { btn.textContent = '↻ Fetching…'; btn.disabled = true; }
  try {
    const r    = await fetch('/api/refresh-data', { method: 'POST' });
    const data = await r.json();
    if (data.status === 'ok') {
      await loadEvidence();
      if (btn) btn.textContent = '✓ Refreshed';
    } else {
      if (btn) btn.textContent = '✗ Error';
      console.error('Refresh error:', data.error);
    }
  } catch(e) {
    if (btn) btn.textContent = '✗ Failed';
    console.error('Refresh failed', e);
  } finally {
    setTimeout(() => { if (btn) { btn.textContent = '↻ Refresh Live Data'; btn.disabled = false; } }, 3000);
  }
}


function renderCorrelation(data) {
  const corr   = data.correlation;
  const labels = data.asset_classes;
  const n      = labels.length;
  const flat   = [];
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++)
      flat.push({ x: j, y: i, v: corr[i][j] });

  if (charts.corr) charts.corr.destroy();
  charts.corr = new Chart(document.getElementById('corrChart').getContext('2d'), {
    type: 'scatter',
    data: {
      datasets: [{
        data: flat,
        backgroundColor: flat.map(p => {
          const v = p.v;
          if (v > 0.6)  return 'rgba(239,68,68,.75)';
          if (v > 0.3)  return 'rgba(245,158,11,.55)';
          if (v > 0)    return 'rgba(59,130,246,.45)';
          if (v > -0.3) return 'rgba(16,185,129,.45)';
          return 'rgba(16,185,129,.75)';
        }),
        pointRadius: 14,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${labels[ctx.raw.y]} vs ${labels[ctx.raw.x]}: ${ctx.raw.v.toFixed(2)}` } },
      },
      scales: {
        x: { min:-.5, max:n-.5, ticks:{ callback: v => labels[v]?.split(' ')[0] || '', color:'#64748b', font:{size:9} }, grid:{color:'#1e2d45'} },
        y: { min:-.5, max:n-.5, ticks:{ callback: v => labels[v]?.split(' ')[0] || '', color:'#64748b', font:{size:9} }, grid:{color:'#1e2d45'} },
      },
    },
  });
}

// ── SENSITIVITY ───────────────────────────────────────────────
async function runSensitivity() {
  const crit = document.getElementById('sensSelect').value;
  try {
    const r    = await fetch('/api/sensitivity', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ criterion: crit }),
    });
    const data = await r.json();

    const labels = data.sweep_values.map(v => (v*100).toFixed(0)+'%');
    const assets = Object.keys(data.allocations);

    if (charts.sens) charts.sens.destroy();
    charts.sens = new Chart(document.getElementById('sensChart').getContext('2d'), {
      type: 'line',
      data: {
        labels,
        datasets: assets.map((a, i) => ({
          label: a,
          data:  data.allocations[a].map(v => +(v*100).toFixed(2)),
          borderColor: COLORS[i],
          backgroundColor: 'transparent',
          tension: .35, pointRadius: 3, borderWidth: 2,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend:{ labels:{ color:'#e2e8f0', font:{size:10} } } },
        scales: {
          x: { title:{ display:true, text: crit + ' Criterion Weight', color:'#64748b' }, ticks:{ color:'#64748b' }, grid:{ color:'#1e2d45' } },
          y: { title:{ display:true, text:'Allocation %', color:'#64748b' }, ticks:{ color:'#64748b', callback: v => v+'%' }, grid:{ color:'#1e2d45' } },
        },
      },
    });
    toast('Sensitivity sweep complete');
  } catch(e) { toast('Sensitivity error: ' + e.message, 'error'); }
}

// ── FUND BENCHMARK ────────────────────────────────────────────
async function runBenchmark() {
  const btn = document.getElementById('bmRunBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Loading…';

  try {
    const r    = await fetch('/api/benchmark');
    const data = await r.json();
    state.benchmarkData = data;

    document.getElementById('bmEmpty').style.display   = 'none';
    document.getElementById('bmContent').style.display = 'block';

    renderBenchmarkOverview(data);
    renderFundProfiles(data);
    renderErrorHeatmap(data);
    renderAllFundsSummary(data);

    // If a fund is pre-selected, show its detail
    const sel = document.getElementById('bmFund').value;
    if (sel && data.funds[sel]) renderFundDetail(sel, data.funds[sel], data.asset_classes);

    toast('Benchmark loaded — ' + data.fund_list.length + ' funds');
  } catch(e) {
    toast('Benchmark error: ' + e.message, 'error');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Load Benchmarks';
  }
}

function updateBenchmarkFund() {
  if (!state.benchmarkData) return;
  const fund = document.getElementById('bmFund').value;
  if (fund && state.benchmarkData.funds[fund]) {
    renderFundDetail(fund, state.benchmarkData.funds[fund], state.benchmarkData.asset_classes);
  } else {
    document.getElementById('bmFundDetail').style.display = 'none';
  }
}

function renderBenchmarkOverview(data) {
  const o = data.overall;
  document.getElementById('bmKPIs').innerHTML = [
    { label:'Funds Benchmarked', value: data.fund_list.length, sub: '2021–2025', color:'#2563eb' },
    { label:'Data Points',       value: o.n_validation_points || (data.fund_list.length * 5), sub: 'fund-year observations', color:'#10b981' },
    { label:'Overall MAE',       value: ((o.avg_mae||0)*100).toFixed(2)+'%', sub:'Mean absolute error', color:'#f59e0b' },
    { label:'Avg Correlation',   value: (o.avg_corr||0).toFixed(3), sub:'Pearson r — model vs actual', color: (o.avg_corr||0) > 0.8 ? '#10b981' : '#f59e0b' },
  ].map(k => `
    <div class="stat-card">
      <div class="stat-label">${k.label}</div>
      <div class="stat-value" style="color:${k.color}">${k.value}</div>
      <div class="stat-sub">${k.sub}</div>
    </div>`).join('');

  // All competitors in 1 chart
  const funds = data.fund_list;
  const maes  = funds.map(f => +((data.funds[f]?.summary?.avg_mae || 0) * 100).toFixed(2));
  const corrs = funds.map(f => +((data.funds[f]?.summary?.avg_corr || 0)).toFixed(3));
  if (charts.bmAll) charts.bmAll.destroy();
  charts.bmAll = new Chart(document.getElementById('bmAllFundsChart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: funds.map(f => f.split(' ')[0]),
      datasets: [
        {
          label: 'MAE % (left axis)',
          data: maes,
          backgroundColor: funds.map((_, i) => FUND_COLORS[i]),
          borderRadius: 5,
          yAxisID: 'y',
        },
        {
          label: 'Correlation (right axis)',
          data: corrs,
          type: 'line',
          borderColor: '#10b981',
          backgroundColor: 'rgba(16,185,129,.1)',
          borderWidth: 2,
          pointRadius: 5,
          tension: .3,
          fill: false,
          yAxisID: 'y2',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins:{ legend:{ labels:{ color:'#e2e8f0', font:{size:10} } } },
      scales: {
        x:  { ticks:{color:'#64748b'}, grid:{color:'#1e2d45'} },
        y:  { ticks:{color:'#64748b', callback:v=>v+'%'}, grid:{color:'#1e2d45'}, title:{display:true,text:'MAE %',color:'#64748b'} },
        y2: { position:'right', ticks:{color:'#10b981'}, grid:{display:false}, min:0, max:1, title:{display:true,text:'Correlation',color:'#10b981'} },
      },
    },
  });
}

function renderFundProfiles(data) {
  const grid = document.getElementById('fundProfileGrid');
  grid.innerHTML = data.fund_list.map((fname, i) => {
    const f = data.funds[fname];
    const m = f.meta;
    const s = f.summary;
    const hitRate = s.hit_rate !== undefined ? (s.hit_rate * 100).toFixed(0) : '—';
    const avgMAE  = s.avg_mae  !== undefined ? (s.avg_mae * 100).toFixed(2) + '%' : '—';
    const avgCorr = s.avg_corr !== undefined ? s.avg_corr.toFixed(3) : '—';
    const gradeHtml = (s.grades || []).map(g => `<span class="grade grade-${g}">${g}</span>`).join(' ');
    return `
      <div class="fund-card" onclick="document.getElementById('bmFund').value='${fname}';updateBenchmarkFund();" style="border-left-color:${FUND_COLORS[i]}">
        <div class="fund-card-name">${fname}</div>
        <div class="fund-card-desc">${m.description}</div>
        <div class="fund-card-stats">
          <div class="fund-stat"><span class="fund-stat-label">AUM</span><span class="fund-stat-value">$${m.aum}B</span></div>
          <div class="fund-stat"><span class="fund-stat-label">Funded</span><span class="fund-stat-value">${m.funded_ratio}%</span></div>
          <div class="fund-stat"><span class="fund-stat-label">Risk</span><span class="fund-stat-value">${m.risk_tolerance}</span></div>
          <div class="fund-stat"><span class="fund-stat-label">Horizon</span><span class="fund-stat-value">${m.horizon}</span></div>
        </div>
        <div class="fund-card-metrics">
          <span class="pill ${parseFloat(avgMAE) < 5 ? 'green' : 'blue'}">MAE ${avgMAE}</span>
          <span class="pill blue">Corr ${avgCorr}</span>
          <span class="pill ${parseInt(hitRate) >= 60 ? 'green' : 'blue'}">Hit ${hitRate}%</span>
        </div>
        <div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">${gradeHtml}</div>
      </div>`;
  }).join('');
}

function renderErrorHeatmap(data) {
  const assets = data.asset_classes;
  const funds  = data.fund_list;
  const hm     = data.heatmap;   // funds × assets

  function heatColor(val) {
    if (val <= 2)  return 'rgba(16,185,129,.55)';
    if (val <= 4)  return 'rgba(59,130,246,.55)';
    if (val <= 6)  return 'rgba(245,158,11,.55)';
    return 'rgba(239,68,68,.65)';
  }

  const shortAsset = a => a.split(' ')[0].substring(0,6);
  let html = '<thead><tr><th style="font-size:.73rem">Fund \\ Asset</th>';
  assets.forEach(a => { html += `<th style="font-size:.73rem">${shortAsset(a)}</th>`; });
  html += '<th style="font-size:.73rem">Avg</th></tr></thead><tbody>';

  hm.forEach((row, fi) => {
    const avg = (row.reduce((s,v) => s+v, 0) / row.length).toFixed(2);
    html += `<tr><td style="font-weight:600;font-size:.78rem;white-space:nowrap">${funds[fi]}</td>`;
    row.forEach(val => {
      html += `<td style="background:${heatColor(val)};text-align:center;font-size:.78rem;font-weight:600;border-radius:3px;padding:6px 4px">${val.toFixed(1)}%</td>`;
    });
    html += `<td style="font-weight:700;font-size:.78rem;text-align:center">${avg}%</td></tr>`;
  });
  html += '</tbody>';
  document.getElementById('errorHeatmap').innerHTML = html;
}

function renderFundDetail(fundName, fundData, assets) {
  document.getElementById('bmFundDetail').style.display = 'block';
  document.getElementById('bmFundDetailName').textContent = fundName + ' — Detailed Analysis';

  const years = fundData.years.sort();
  const latestYear = years[years.length - 1];
  const yd = fundData.year_data;

  // Model vs Actual — latest year (grouped bar)
  const modelVals  = assets.map(a => (yd[latestYear]?.model[a] || 0) * 100);
  const actualVals = assets.map(a => (yd[latestYear]?.actual[a] || 0) * 100);

  if (charts.bmCompare) charts.bmCompare.destroy();
  charts.bmCompare = new Chart(document.getElementById('bmCompareChart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: assets.map(a => a.split(' ')[0]),
      datasets: [
        { label: 'Model ' + latestYear,  data: modelVals,  backgroundColor: 'rgba(37,99,235,.75)', borderRadius: 4 },
        { label: 'Actual ' + latestYear, data: actualVals, backgroundColor: 'rgba(16,185,129,.75)', borderRadius: 4 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend:{ labels:{ color:'#e2e8f0', font:{size:10} } } },
      scales: {
        x: { ticks:{color:'#64748b',font:{size:9}}, grid:{color:'#1e2d45'} },
        y: { ticks:{color:'#64748b', callback: v => v+'%'}, grid:{color:'#1e2d45'} },
      },
    },
  });

  // MAE over time (line)
  if (charts.bmTime) charts.bmTime.destroy();
  charts.bmTime = new Chart(document.getElementById('bmTimeChart').getContext('2d'), {
    type: 'line',
    data: {
      labels: years,
      datasets: [
        {
          label: 'MAE %',
          data:  years.map(y => yd[y]?.mae || 0),
          borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.1)',
          tension: .4, pointRadius: 5, fill: true,
        },
        {
          label: 'Correlation',
          data:  years.map(y => (yd[y]?.correlation || 0) * 100),
          borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,.1)',
          tension: .4, pointRadius: 5, fill: false,
          yAxisID: 'y2',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend:{ labels:{ color:'#e2e8f0', font:{size:10} } } },
      scales: {
        x:  { ticks:{color:'#64748b'}, grid:{color:'#1e2d45'} },
        y:  { ticks:{color:'#ef4444', callback: v => v+'%'}, grid:{color:'#1e2d45'}, title:{display:true,text:'MAE %',color:'#ef4444'} },
        y2: { position:'right', ticks:{color:'#10b981', callback: v => v.toFixed(0)+'%'}, grid:{drawOnChartArea:false}, title:{display:true,text:'Corr ×100',color:'#10b981'} },
      },
    },
  });

  // Year table
  document.getElementById('bmYearTable').innerHTML = years.map(y => {
    const d = yd[y];
    if (!d) return '';
    return `<tr>
      <td class="forecast-year">${y}</td>
      <td>${d.scenario}</td>
      <td><span class="${d.mae < 5 ? 'positive' : d.mae < 8 ? '' : 'negative'}">${d.mae.toFixed(2)}%</span></td>
      <td>${d.rmse.toFixed(2)}%</td>
      <td>${d.correlation.toFixed(3)}</td>
      <td><span class="grade grade-${d.grade}">${d.grade}</span></td>
      <td style="font-size:.78rem;color:var(--muted)">${d.max_dev_asset} (${d.max_dev_pct}%)</td>
    </tr>`;
  }).join('');

  // Asset error bars
  const ae = fundData.asset_errors;
  const maxErr = Math.max(...Object.values(ae).map(e => e.mean_error));
  document.getElementById('bmAssetErrors').innerHTML = assets.map((a, i) => `
    <div class="alloc-row">
      <div class="alloc-label" style="font-size:.8rem">${a}</div>
      <div class="alloc-bar-wrap">
        <div class="alloc-bar" style="width:${maxErr > 0 ? (ae[a].mean_error/maxErr*100).toFixed(1) : 0}%;background:${ae[a].mean_error > 6 ? '#ef4444' : ae[a].mean_error > 4 ? '#f59e0b' : ae[a].mean_error > 2 ? '#3b82f6' : '#10b981'}"></div>
      </div>
      <div class="alloc-pct" style="font-size:.78rem">${ae[a].mean_error.toFixed(2)}%</div>
      <div class="alloc-usd" style="font-size:.72rem;color:var(--muted)">max ${ae[a].max_error.toFixed(1)}%</div>
    </div>`).join('');

  // Scatter: model vs actual (all years × all assets)
  const scatterPoints = [];
  years.forEach((y, yi) => {
    if (!yd[y]) return;
    assets.forEach(a => {
      scatterPoints.push({
        x: (yd[y].actual[a] || 0) * 100,
        y: (yd[y].model[a] || 0) * 100,
        label: `${a} (${y})`,
      });
    });
  });

  // Perfect-fit diagonal
  const allVals = scatterPoints.map(p => Math.max(p.x, p.y));
  const diagMax = Math.max(...allVals, 10);

  if (charts.bmScatter) charts.bmScatter.destroy();
  charts.bmScatter = new Chart(document.getElementById('bmScatterChart').getContext('2d'), {
    type: 'scatter',
    data: {
      datasets: [
        {
          label: 'Model vs Actual',
          data: scatterPoints,
          backgroundColor: 'rgba(37,99,235,.6)',
          pointRadius: 6,
        },
        {
          label: 'Perfect Fit',
          data: [{ x: 0, y: 0 }, { x: diagMax, y: diagMax }],
          type: 'line',
          borderColor: 'rgba(16,185,129,.5)',
          borderDash: [6, 4],
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#e2e8f0', font: { size: 10 } } },
        tooltip: { callbacks: { label: ctx => ctx.raw.label ? `${ctx.raw.label}: actual=${ctx.raw.x.toFixed(1)}% model=${ctx.raw.y.toFixed(1)}%` : 'Diagonal' } },
      },
      scales: {
        x: { title:{ display:true, text:'Actual Allocation %', color:'#64748b' }, ticks:{color:'#64748b', callback: v => v+'%'}, grid:{color:'#1e2d45'} },
        y: { title:{ display:true, text:'Model Allocation %', color:'#64748b' }, ticks:{color:'#64748b', callback: v => v+'%'}, grid:{color:'#1e2d45'} },
      },
    },
  });

  // Scroll to detail section
  document.getElementById('bmFundDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderAllFundsSummary(data) {
  document.getElementById('bmAllFunds').innerHTML = data.fund_list.map((fname, i) => {
    const f = data.funds[fname];
    const m = f.meta;
    const s = f.summary;
    const hitRate = s.hit_rate !== undefined ? (s.hit_rate * 100).toFixed(0) + '%' : '—';
    const avgMAE  = s.avg_mae  !== undefined ? (s.avg_mae * 100).toFixed(2) + '%' : '—';
    const avgCorr = s.avg_corr !== undefined ? s.avg_corr.toFixed(3) : '—';
    const gradeHtml = (s.grades || []).map(g => `<span class="grade grade-${g}">${g}</span>`).join(' ');
    return `<tr>
      <td style="font-weight:600">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${FUND_COLORS[i]};margin-right:6px"></span>
        <a href="#" onclick="document.getElementById('bmFund').value='${fname}';updateBenchmarkFund();return false;" style="color:var(--accent2)">${fname}</a>
      </td>
      <td>$${m.aum}B</td>
      <td>${m.funded_ratio}%</td>
      <td>${m.risk_tolerance}</td>
      <td><span class="${parseFloat(avgMAE) < 5 ? 'positive' : 'negative'}">${avgMAE}</span></td>
      <td>${avgCorr}</td>
      <td><span class="pill ${parseInt(hitRate) >= 60 ? 'green' : 'blue'}">${hitRate}</span></td>
      <td>${gradeHtml}</td>
    </tr>`;
  }).join('');
}

// ── VALIDATION ────────────────────────────────────────────────
async function runValidation() {
  const btn = event.target;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running…';

  try {
    const r    = await fetch('/api/validate');
    const data = await r.json();

    document.getElementById('valEmpty').style.display   = 'none';
    document.getElementById('valContent').style.display = 'block';

    const s = data.overall;
    document.getElementById('valKPIs').innerHTML = [
      { label:'Data Points', value: s.n_validation_points, sub: s.n_funds + ' funds × 5 years' },
      { label:'Avg MAE',     value: (s.avg_mae*100).toFixed(2)+'%', sub:'Mean absolute error' },
      { label:'Avg Corr',    value: s.avg_corr.toFixed(3), sub:'Pearson correlation' },
      { label:'CR Violations', value: s.grade_distribution.F, sub:'F-grade matrices' },
    ].map(k => `<div class="stat-card"><div class="stat-label">${k.label}</div><div class="stat-value">${k.value}</div><div class="stat-sub">${k.sub}</div></div>`).join('');

    document.getElementById('valSummary').innerHTML = Object.entries(data.summaries).map(([fund, s]) => `
      <tr>
        <td style="font-weight:600">${fund}</td>
        <td>${s.avg_mae}%</td>
        <td>${s.avg_corr}</td>
        <td><span class="pill ${s.hit_rate >= 60 ? 'green' : 'blue'}">${s.hit_rate}%</span></td>
        <td>${s.grades.map(g => `<span class="grade grade-${g}">${g}</span>`).join(' ')}</td>
      </tr>`).join('');

    const funds = Object.keys(data.summaries);
    if (charts.val) charts.val.destroy();
    charts.val = new Chart(document.getElementById('valChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: funds,
        datasets: [{
          label: 'Avg MAE %',
          data: funds.map(f => data.summaries[f].avg_mae),
          backgroundColor: FUND_COLORS.slice(0, funds.length), borderRadius: 5,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins:{ legend:{display:false} },
        scales: {
          x:{ ticks:{color:'#64748b',font:{size:9}}, grid:{color:'#1e2d45'} },
          y:{ ticks:{color:'#64748b',callback:v=>v+'%'}, grid:{color:'#1e2d45'} },
        },
      },
    });

    document.getElementById('valRows').innerHTML = data.rows.map(r => `
      <tr>
        <td style="font-weight:600">${r.fund}</td>
        <td class="forecast-year">${r.year}</td>
        <td>${r.scenario}</td>
        <td>${r.mae}%</td>
        <td>${r.rmse}%</td>
        <td>${r.correlation}</td>
        <td><span class="grade grade-${r.grade}">${r.grade}</span></td>
        <td style="font-size:.78rem;color:var(--muted)">${r.max_dev_asset} (${r.max_dev_pct}%)</td>
      </tr>`).join('');

    toast('Validation complete — ' + s.n_validation_points + ' observations');
  } catch(e) { toast('Validation error: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.innerHTML = 'Run Full Validation (40 points)'; }
}

// ── FORECAST ──────────────────────────────────────────────────
async function runForecast() {
  const fund = document.getElementById('foreFund').value;
  const btn  = event.target;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';

  try {
    const r    = await fetch('/api/forecast?fund=' + encodeURIComponent(fund));
    const data = await r.json();

    document.getElementById('foreEmpty').style.display   = 'none';
    document.getElementById('foreContent').style.display = 'block';

    const af = data.forecast.annual_forecasts;
    const years = Object.keys(af).map(Number).sort();
    const assets = state.constants?.asset_classes || Object.keys(af[years[0]].probability_weighted_allocation);

    // Histogram: distribution of expected portfolio returns across years
    const returnValues = years.map(y => af[y].portfolio_expected_return_pct);
    const histBins = [0,2,4,6,8,10,12,14];
    const histCounts = histBins.slice(0,-1).map((lo, i) => {
      const hi = histBins[i+1];
      return returnValues.filter(v => v >= lo && v < hi).length;
    });
    const histLabels = histBins.slice(0,-1).map((lo,i) => `${lo}–${histBins[i+1]}%`);

    if (charts.fore) charts.fore.destroy();
    charts.fore = new Chart(document.getElementById('foreChart').getContext('2d'), {
      type: 'bar',
      data: {
        labels: histLabels,
        datasets: [{
          label: 'Years in return range',
          data: histCounts,
          backgroundColor: histCounts.map((_,i) => COLORS[i % COLORS.length]),
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins:{
          legend:{ display: false },
          title:{ display:true, text:'Expected Return Distribution (2026–2030)', color:'#e2e8f0', font:{size:12} },
        },
        scales: {
          x:{ ticks:{color:'#64748b'}, grid:{color:'#1e2d45'}, title:{display:true, text:'Return Range', color:'#64748b'} },
          y:{ ticks:{color:'#64748b', stepSize:1}, grid:{color:'#1e2d45'}, title:{display:true, text:'Number of Years', color:'#64748b'} },
        },
      },
    });

    if (charts.foreRet) charts.foreRet.destroy();
    charts.foreRet = new Chart(document.getElementById('foreRetChart').getContext('2d'), {
      type: 'line',
      data: {
        labels: years,
        datasets: [{
          label: 'Expected Return %',
          data:  years.map(y => af[y].portfolio_expected_return_pct),
          borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,.1)',
          tension: .4, pointRadius: 5, fill: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins:{ legend:{ labels:{ color:'#e2e8f0' } } },
        scales: {
          x:{ ticks:{color:'#64748b'}, grid:{color:'#1e2d45'} },
          y:{ ticks:{color:'#64748b', callback:v=>v+'%'}, grid:{color:'#1e2d45'} },
        },
      },
    });

    document.getElementById('foreBody').innerHTML = assets.map(a => `
      <tr>
        <td style="font-weight:600">${a}</td>
        ${years.map(y => `<td>${pct(af[y].probability_weighted_allocation[a])}</td>`).join('')}
      </tr>`).join('');

    const attr = data.attribution.returns_attribution;
    document.getElementById('attrBody').innerHTML = Object.entries(attr).map(([yr, d]) => `
      <tr>
        <td class="forecast-year">${yr}</td>
        <td>${d.scenario}</td>
        <td class="${d.actual_portfolio_return_pct >= 0 ? 'positive' : 'negative'}">${sign(d.actual_portfolio_return_pct)}%</td>
        <td class="${d.model_portfolio_return_pct >= 0 ? 'positive' : 'negative'}">${sign(d.model_portfolio_return_pct)}%</td>
        <td class="${d.difference_pct >= 0 ? 'positive' : 'negative'}">${d.difference_pct >= 0 ? '+' : ''}${d.difference_pct.toFixed(2)}%</td>
      </tr>`).join('');

    toast('Forecast generated for ' + fund);
  } catch(e) { toast('Forecast error: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.innerHTML = 'Generate Forecast'; }
}

// ── PRACTITIONER STRESS TEST ─────────────────────────────────

let stressProfiles = {};
let saatyOptions   = [];
let stressState    = {};   // current criteria values being edited

const CRITERIA_PAIRS = [
  'Return vs Risk', 'Return vs Liquidity',
  'Risk vs Liquidity',
];

async function initStressTest() {
  try {
    const r    = await fetch('/api/practitioner-profiles');
    const data = await r.json();
    stressProfiles = data.profiles || {};
    saatyOptions   = data.saaty_options || [];

    // Populate profile dropdown
    const sel = document.getElementById('practitionerProfile');
    if (sel) {
      Object.keys(stressProfiles).forEach(name => {
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        sel.appendChild(opt);
      });
    }

    // Build criteria input grid
    renderCriteriaInputGrid();
  } catch(e) { console.error('initStressTest failed', e); }
}

function renderCriteriaInputGrid() {
  // Default values = Liberty Bell base
  const defaults = {
    'Return vs Risk': 2, 'Return vs Liquidity': 5,
    'Risk vs Liquidity': 3,
  };
  if (!stressState || !Object.keys(stressState).length) stressState = {...defaults};

  const grid = document.getElementById('criteriaInputsGrid');
  if (!grid) return;
  grid.innerHTML = CRITERIA_PAIRS.map(pair => {
    const cur = stressState[pair] || 1;
    const opts = saatyOptions.length
      ? saatyOptions.map(o => `<option value="${o.value}" ${Math.abs(o.value - cur) < 0.001 ? 'selected' : ''}>${o.label}</option>`).join('')
      : `<option value="${cur}" selected>${cur}</option>`;
    return `<div style="background:var(--surface2);padding:10px 14px;border-radius:8px;border:1px solid var(--border)">
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:6px;font-weight:500">${pair}</div>
      <select class="form-control" style="width:100%;font-size:.8rem" id="sc_${pair.replace(/ /g,'_').replace(/\//g,'_')}"
              onchange="stressState['${pair}'] = parseFloat(this.value); updateStressCR()">
        ${opts}
      </select>
    </div>`;
  }).join('');
  updateStressCR();
}

function loadPractitionerProfile() {
  const sel   = document.getElementById('practitionerProfile');
  const name  = sel?.value;
  if (!name || !stressProfiles[name]) return;
  const p = stressProfiles[name];

  // Update stressState
  Object.entries(p.criteria).forEach(([key, val]) => {
    stressState[key] = val;
  });
  renderCriteriaInputGrid();

  // Show profile desc
  const desc = document.getElementById('profileDesc');
  if (desc) {
    desc.style.display = 'block';
    desc.innerHTML = `<strong>${name}</strong> — ${p.description}<br><span style="color:var(--accent2)">Archetype: ${p.archetype}</span><br><span style="opacity:.7">Priority: ${p.priority}</span>`;
  }
}

function updateStressCR() {
  // Quick client-side CR estimate isn't feasible without numpy — just show current values
  const bar = document.getElementById('stressCrBar');
  if (!bar) return;
  bar.style.display = 'flex';
  bar.style.background = 'rgba(37,99,235,.08)';
  bar.style.border = '1px solid rgba(37,99,235,.2)';
  const vals = Object.entries(stressState).map(([k,v]) => `${k}: <strong>${Number(v).toFixed(3)}</strong>`).join(' · ');
  bar.innerHTML = `<span style="font-size:.75rem;color:var(--muted)">${vals}</span>`;
}

async function runStressTest() {
  const btn = document.getElementById('btnStressTest');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running…';

  // Build criteria dict
  const criteria = {};
  CRITERIA_PAIRS.forEach(pair => {
    criteria[pair] = parseFloat(stressState[pair] || 1);
  });

  try {
    const r    = await fetch('/api/stress-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criteria }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    renderStressResults(data);
    toast(`Stress test complete — ${data.n_assets_shifted_gt1pct} assets shifted >1pp vs base`);
  } catch(e) { toast('Stress test failed: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.innerHTML = '▶ Run Stress Test'; }
}

function renderStressResults(data) {
  document.getElementById('stressResults').style.display = 'block';
  document.getElementById('stressResults').scrollIntoView({ behavior: 'smooth', block: 'start' });

  const assets   = Object.keys(data.base_weights);
  const baseVals = assets.map(a => +(data.base_weights[a] * 100).toFixed(1));
  const custVals = assets.map(a => +(data.custom_weights[a] * 100).toFixed(1));
  const deltas   = assets.map(a => +(data.deltas[a] * 100).toFixed(1));

  // Side-by-side comparison chart
  if (charts.stressCompare) charts.stressCompare.destroy();
  charts.stressCompare = new Chart(document.getElementById('stressCompareChart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: assets.map(a => a.split(' ').slice(-1)[0]),
      datasets: [
        { label: 'Base (Research)',     data: baseVals, backgroundColor: 'rgba(37,99,235,.7)' },
        { label: 'Practitioner Input',  data: custVals, backgroundColor: 'rgba(16,185,129,.7)' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins:{ legend:{ labels:{ color:'#e2e8f0', font:{size:9} } } },
      scales: {
        x:{ ticks:{color:'#64748b',font:{size:9}}, grid:{color:'#1e2d45'} },
        y:{ ticks:{color:'#64748b', callback:v=>v+'%'}, grid:{color:'#1e2d45'} },
      },
    },
  });

  // Delta chart
  if (charts.stressDelta) charts.stressDelta.destroy();
  charts.stressDelta = new Chart(document.getElementById('stressDeltaChart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: assets.map(a => a.split(' ').slice(-1)[0]),
      datasets: [{
        label: 'Δ pp (Practitioner − Base)',
        data:  deltas,
        backgroundColor: deltas.map(d => d >= 0 ? 'rgba(16,185,129,.75)' : 'rgba(239,68,68,.75)'),
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins:{ legend:{ labels:{ color:'#e2e8f0' } } },
      scales: {
        x:{ ticks:{color:'#64748b',font:{size:9}}, grid:{color:'#1e2d45'} },
        y:{ ticks:{color:'#64748b', callback:v=>(v>=0?'+':'')+v+'pp'}, grid:{color:'#1e2d45'} },
      },
    },
  });

  // Criteria weight comparison
  const crits    = Object.keys(data.base_criteria_weights || {});
  const baseCw   = crits.map(c => +((data.base_criteria_weights[c]||0)*100).toFixed(1));
  const custCw   = crits.map(c => +((data.custom_criteria_weights[c]||0)*100).toFixed(1));
  if (charts.stressCrit) charts.stressCrit.destroy();
  charts.stressCrit = new Chart(document.getElementById('stressCritChart').getContext('2d'), {
    type: 'radar',
    data: {
      labels: crits,
      datasets: [
        { label: 'Base',         data: baseCw, borderColor:'rgba(37,99,235,.9)',  backgroundColor:'rgba(37,99,235,.1)',  pointRadius:3 },
        { label: 'Practitioner', data: custCw, borderColor:'rgba(16,185,129,.9)', backgroundColor:'rgba(16,185,129,.1)', pointRadius:3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins:{ legend:{ labels:{ color:'#e2e8f0', font:{size:10} } } },
      scales:{ r:{ ticks:{ color:'#64748b', font:{size:9}, backdropColor:'transparent' }, grid:{ color:'#1e2d45' }, angleLines:{ color:'#1e2d45' }, pointLabels:{ color:'#94a3b8', font:{size:10} } } },
    },
  });

  // CR badge
  const crBar  = document.getElementById('stressCrBar');
  const crVal  = data.criteria_cr;
  const crGrad = data.criteria_grade;
  const crColor = crGrad === 'A' ? '#00d282' : (crGrad === 'B' ? '#fabc00' : (crGrad === 'C' ? '#f97316' : '#ef4444'));
  if (crBar) {
    crBar.style.background = `rgba(0,0,0,.2)`;
    crBar.style.border     = `1px solid ${crColor}44`;
    crBar.innerHTML = `<span style="background:${crColor};color:#0a0f1e;padding:2px 9px;border-radius:12px;font-weight:700;font-size:.75rem">Grade ${crGrad}</span>
      <span>Criteria CR = ${crVal.toFixed(4)}</span>
      <span style="opacity:.6">${data.cr_pass ? '✓ Passes CR ≤ 0.10' : '✗ Fails CR threshold — auto-repaired'}</span>
      <span style="margin-left:auto;opacity:.6">Overall: ${data.custom_overall_grade}</span>
      ${data.rank_reversal ? `<span style="color:#f97316">⚠ Rank reversal detected</span>` : ''}`;
  }

  // Sensitivity table
  const sensBody = document.getElementById('stressSensBody');
  if (sensBody && data.sensitivity_map) {
    sensBody.innerHTML = Object.entries(data.sensitivity_map).map(([pair, sv]) => {
      const up   = sv.impacts?.up_one_step;
      const down = sv.impacts?.down_one_step;
      return `<tr>
        <td style="font-size:.78rem;font-weight:500">${pair}</td>
        <td style="font-weight:600;color:var(--accent2)">${sv.current_display}</td>
        <td style="font-size:.75rem">${up   ? `${up.saaty_display} → ${up.max_shift_asset.split(' ').pop()} ${up.max_shift_pct > 0 ? '+' : ''}${up.max_shift_pct}pp` : '—'}</td>
        <td style="font-size:.75rem">${down ? `${down.saaty_display} → ${down.max_shift_asset.split(' ').pop()} ${down.max_shift_pct > 0 ? '+' : ''}${down.max_shift_pct}pp` : '—'}</td>
        <td style="font-size:.75rem;color:var(--accent)">${data.largest_shift_asset || '—'}</td>
      </tr>`;
    }).join('');
  }

  // Full allocation table
  const allocBody = document.getElementById('stressAllocBody');
  if (allocBody) {
    allocBody.innerHTML = assets.map(a => {
      const base  = (data.base_weights[a]   * 100).toFixed(1);
      const cust  = (data.custom_weights[a] * 100).toFixed(1);
      const delta = (data.deltas[a] * 100).toFixed(1);
      const isUp  = data.deltas[a] > 0.005;
      const isDn  = data.deltas[a] < -0.005;
      return `<tr>
        <td style="font-weight:600">${a}</td>
        <td>${base}%</td>
        <td style="color:var(--accent2)">${cust}%</td>
        <td style="color:${isUp ? 'var(--green)' : isDn ? 'var(--red)' : 'var(--muted)'}">${delta >= 0 ? '+' : ''}${delta}pp</td>
        <td>${isUp ? '↑ Increase' : isDn ? '↓ Decrease' : '— Unchanged'}</td>
      </tr>`;
    }).join('');
  }
}

// ── BOOTSTRAP CI FORECAST ────────────────────────────────────
let ciData = null;
const CI_COLORS = {
  band: 'rgba(124,58,237,.15)',
  p50:  '#7c3aed',
  line: 'rgba(124,58,237,.5)',
};

async function runCIForecast() {
  const fund = document.getElementById('foreFund').value;
  const btn  = document.getElementById('btnCIForecast');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Bootstrapping…';

  document.getElementById('foreEmpty').style.display   = 'none';
  document.getElementById('foreContent').style.display = 'none';
  document.getElementById('ciContent').style.display   = 'none';

  try {
    const r    = await fetch(`/api/forecast-ci?fund=${encodeURIComponent(fund)}&n_sims=400`);
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    ciData = data;
    renderCIForecast(data);
    toast(`Bootstrap CI forecast complete — ${data.n_simulations} sims/year`);
  } catch(e) { toast('CI Forecast failed: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.innerHTML = '◈ Bootstrap CI (N=400)'; }
}

function renderCIForecast(data) {
  document.getElementById('ciContent').style.display = 'block';

  // Methodology badge
  const badge = document.getElementById('ciMethodBadge');
  if (badge) badge.innerHTML = `<strong style="color:#7c3aed">Methodology:</strong> ${data.methodology}`;

  // Populate fan chart asset selector
  const sel = document.getElementById('ciFanAsset');
  if (sel && sel.options.length <= 1) {
    data.asset_classes.forEach(a => {
      const o = document.createElement('option'); o.value = a; o.textContent = a; sel.appendChild(o);
    });
  }

  renderFanChart();
  renderPortReturnFan(data);
  renderAttributionChart(data);
  renderCIBandTable(data);
  renderIRTable(data);

  // KPI row
  const kpiRow = document.getElementById('ciKpiRow');
  if (kpiRow) {
    const year1 = data.years[0];
    const pb    = data.port_return_bands[String(year1)];
    const firstAttr = data.attribution[String(year1)];
    kpiRow.innerHTML = [
      { label: '2026 Portfolio P50 Return',   val: pb?.P50?.toFixed(1) + '%' || '—',     sub: `P10–P90: ${pb?.P10?.toFixed(1)}%–${pb?.P90?.toFixed(1)}%` },
      { label: 'Dominant Uncertainty Source', val: firstAttr?.dominant_source || '—',    sub: `${firstAttr?.scenario_variance_pct}% scenario · ${firstAttr?.criteria_variance_pct}% judgment` },
      { label: 'Simulations per Year',        val: data.n_simulations.toLocaleString(),   sub: 'Bootstrap resamples' },
      { label: 'Forecast Horizon',            val: `${data.years[0]}–${data.years[data.years.length-1]}`, sub: 'with growing uncertainty bands' },
    ].map(k => `<div class="kpi-card"><div class="kpi-label">${k.label}</div><div class="kpi-value" style="font-size:1.1rem">${k.val}</div><div class="kpi-sub">${k.sub}</div></div>`).join('');
  }
}

function renderFanChart() {
  if (!ciData) return;
  const assetSel = document.getElementById('ciFanAsset')?.value || 'all';
  const assets   = assetSel === 'all' ? ciData.asset_classes : [assetSel];
  const container = document.getElementById('ciFanContainer');
  if (!container) return;

  // Destroy existing fan charts
  Object.keys(charts).filter(k => k.startsWith('fan_')).forEach(k => {
    charts[k]?.destroy(); delete charts[k];
  });
  container.innerHTML = '';

  assets.forEach(asset => {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'background:var(--surface2);border-radius:10px;padding:12px;border:1px solid var(--border)';
    wrap.innerHTML = `<div style="font-size:.8rem;font-weight:600;margin-bottom:8px;color:var(--text)">${asset}</div>
                      <div style="height:160px"><canvas id="fan_${asset.replace(/ /g,'_')}"></canvas></div>`;
    container.appendChild(wrap);

    const labels = ciData.years;
    const bands  = ciData.asset_bands[asset];
    if (!bands) return;

    const p10 = labels.map(y => +(bands[y]?.P10 * 100 || 0).toFixed(1));
    const p25 = labels.map(y => +(bands[y]?.P25 * 100 || 0).toFixed(1));
    const p50 = labels.map(y => +(bands[y]?.P50 * 100 || 0).toFixed(1));
    const p75 = labels.map(y => +(bands[y]?.P75 * 100 || 0).toFixed(1));
    const p90 = labels.map(y => +(bands[y]?.P90 * 100 || 0).toFixed(1));

    const chartId = `fan_${asset.replace(/ /g,'_')}`;
    charts[chartId] = new Chart(document.getElementById(chartId).getContext('2d'), {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'P90', data: p90, borderColor:'transparent', backgroundColor:'rgba(124,58,237,.10)', fill:'+1', pointRadius:0 },
          { label: 'P75', data: p75, borderColor:'transparent', backgroundColor:'rgba(124,58,237,.15)', fill:'+1', pointRadius:0 },
          { label: 'P50', data: p50, borderColor:'#7c3aed',     backgroundColor:'transparent',          fill:false, borderWidth:2, pointRadius:3, pointBackgroundColor:'#7c3aed' },
          { label: 'P25', data: p25, borderColor:'transparent', backgroundColor:'rgba(124,58,237,.15)', fill:'-1', pointRadius:0 },
          { label: 'P10', data: p10, borderColor:'transparent', backgroundColor:'rgba(124,58,237,.10)', fill:'-1', pointRadius:0 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins:{ legend:{ display:false } },
        scales: {
          x:{ ticks:{color:'#64748b',font:{size:8}}, grid:{color:'#1e2d45'} },
          y:{ ticks:{color:'#64748b',font:{size:8},callback:v=>v+'%'}, grid:{color:'#1e2d45'} },
        },
      },
    });
  });
}

function renderPortReturnFan(data) {
  const pb     = data.port_return_bands;
  const labels = data.years;
  const p10 = labels.map(y => pb[y]?.P10);
  const p25 = labels.map(y => pb[y]?.P25);
  const p50 = labels.map(y => pb[y]?.P50);
  const p75 = labels.map(y => pb[y]?.P75);
  const p90 = labels.map(y => pb[y]?.P90);

  if (charts.ciPortRet) charts.ciPortRet.destroy();
  charts.ciPortRet = new Chart(document.getElementById('ciPortRetChart').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'P90', data: p90, borderColor:'transparent', backgroundColor:'rgba(16,185,129,.10)', fill:'+1', pointRadius:0 },
        { label: 'P75', data: p75, borderColor:'transparent', backgroundColor:'rgba(16,185,129,.15)', fill:'+1', pointRadius:0 },
        { label: 'P50 (Median)', data: p50, borderColor:'#10b981', backgroundColor:'transparent', fill:false, borderWidth:2.5, pointRadius:4, pointBackgroundColor:'#10b981' },
        { label: 'P25', data: p25, borderColor:'transparent', backgroundColor:'rgba(16,185,129,.15)', fill:'-1', pointRadius:0 },
        { label: 'P10', data: p10, borderColor:'transparent', backgroundColor:'rgba(16,185,129,.10)', fill:'-1', pointRadius:0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins:{ legend:{ labels:{ color:'#e2e8f0', font:{size:9}, filter: i => i.text !== 'P90' && i.text !== 'P10' && i.text !== 'P25' && i.text !== 'P75' } } },
      scales: {
        x:{ ticks:{color:'#64748b'}, grid:{color:'#1e2d45'} },
        y:{ ticks:{color:'#64748b',callback:v=>v+'%'}, grid:{color:'#1e2d45'} },
      },
    },
  });
}

function renderAttributionChart(data) {
  const labels  = Object.keys(data.attribution);
  const sc_pct  = labels.map(y => data.attribution[y].scenario_variance_pct);
  const cr_pct  = labels.map(y => data.attribution[y].criteria_variance_pct);
  const ret_pct = labels.map(y => data.attribution[y].return_variance_pct);

  if (charts.ciAttr) charts.ciAttr.destroy();
  charts.ciAttr = new Chart(document.getElementById('ciAttrChart').getContext('2d'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Macro Scenario',     data: sc_pct,  backgroundColor: 'rgba(239,68,68,.75)',   stack: 'attr' },
        { label: 'Judgment / Criteria', data: cr_pct,  backgroundColor: 'rgba(250,188,0,.75)',  stack: 'attr' },
        { label: 'Return Variability',  data: ret_pct, backgroundColor: 'rgba(124,58,237,.7)',  stack: 'attr' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins:{ legend:{ labels:{ color:'#e2e8f0', font:{size:9} } } },
      scales: {
        x:{ stacked:true, ticks:{color:'#64748b'}, grid:{color:'#1e2d45'} },
        y:{ stacked:true, max:100, ticks:{color:'#64748b',callback:v=>v+'%'}, grid:{color:'#1e2d45'} },
      },
    },
  });

  // Text interpretation
  const attrText = document.getElementById('ciAttrText');
  if (attrText) {
    attrText.innerHTML = labels.map(y => {
      const a = data.attribution[y];
      return `<div style="margin-bottom:6px"><strong>${y}:</strong> ${a.interpretation}</div>`;
    }).join('');
  }
}

function renderCIBandTable(data) {
  const body = document.getElementById('ciBandBody');
  if (!body) return;
  body.innerHTML = data.asset_classes.map(asset => {
    const b = data.asset_bands[asset];
    function bandCell(year) {
      const d = b[String(year)];
      if (!d) return '<td>—</td><td>—</td>';
      return `<td style="font-weight:600;color:var(--accent2)">${(d.P50*100).toFixed(1)}%</td>
              <td style="font-size:.75rem;color:var(--muted)">${(d.P10*100).toFixed(1)}%–${(d.P90*100).toFixed(1)}%</td>`;
    }
    return `<tr><td style="font-weight:600">${asset}</td>${bandCell(2026)}${bandCell(2028)}${bandCell(2030)}</tr>`;
  }).join('');
}

function renderIRTable(data) {
  const body = document.getElementById('ciIrBody');
  if (!body) return;
  body.innerHTML = data.asset_classes.map(asset => {
    const irs = data.information_ratios?.[asset] || {};
    const irCell = y => {
      const d = irs[String(y)];
      if (!d) return '<td style="color:var(--muted)">—</td>';
      const col = d.ir > 1.0 ? 'var(--green)' : d.ir > 0 ? 'var(--accent2)' : 'var(--red)';
      return `<td style="color:${col};font-weight:600">${d.ir.toFixed(2)}</td>`;
    };
    return `<tr><td style="font-weight:600">${asset}</td>${[2026,2027,2028,2029,2030].map(irCell).join('')}</tr>`;
  }).join('');
}

// Init stress test on page load
initStressTest();

// ── CHATBOT ───────────────────────────────────────────────────
const modeDescs = {
  ADVISOR:   'Tells you exactly how much to invest in each asset class based on your AHP model, challenges your choices, and compares to real pension funds.',
  CHALLENGE: 'AI actively argues against your choices using empirical data — forces you to justify every allocation decision.',
  COACH:     'Guides you through the AHP decision with Socratic questions — without giving direct answers.',
  AUDIT:     'Systematically reviews all pairwise matrices, grades each CR, and pinpoints which comparisons to fix.',
  FORECAST:  'Stress-tests your allocation under 5 future scenarios (2026–2030) and identifies which weights would change.',
};
document.getElementById('chatMode')?.addEventListener('change', function() {
  document.getElementById('modeDesc').textContent = modeDescs[this.value];
});

function sendQuick(msg) {
  document.getElementById('chatInput').value = msg;
  sendChat();
}

function buildModelContext() {
  // Build a rich context object from current state.result for the advisor
  if (!state.result) return {};
  const r = state.result;
  const fundEl    = document.getElementById('cfgFund');
  const aumEl     = document.getElementById('cfgAum');
  const scenEl    = document.getElementById('cfgScenario');
  const fundedEl  = document.getElementById('cfgFunded');
  return {
    fund_name:           fundEl?.value || 'Unknown Fund',
    aum:                 parseFloat(aumEl?.value || 0),
    scenario:            scenEl?.value || 'Steady Growth',
    funded_ratio:        parseFloat(fundedEl?.value || 0),
    overall_grade:       r.overall_grade,
    constrained_weights: r.constrained_weights,
    dollar_allocation:   r.dollar_allocation,
    criteria_weights:    r.criteria_weights,
    consistency_results: r.consistency_results,
    rank_reversal_flag:  r.rank_reversal_flag,
    mc_summary:          state.mc || null,
  };
}

function updateChatContextStatus() {
  const el = document.getElementById('chatContextStatus');
  if (!el) return;
  if (state.result) {
    const r = state.result;
    const top = Object.entries(r.constrained_weights).sort((a,b) => b[1]-a[1])[0];
    const aum = parseFloat(document.getElementById('cfgAum')?.value || 0);
    el.innerHTML = `<span style="color:var(--green)">✓ Model loaded</span> — Grade ${r.overall_grade} · $${aum}B AUM · Top: ${top[0].split(' ')[0]} (${pct(top[1])})`;
  } else {
    el.innerHTML = 'No model run yet — click <strong>▶ Run Model</strong> first';
  }
}

async function sendChat() {
  const input     = document.getElementById('chatInput');
  const apiKeyEl  = document.getElementById('apiKey');
  const msg       = input?.value.trim();
  const apiKey    = apiKeyEl?.value.trim();
  const mode      = document.getElementById('chatMode')?.value || 'ADVISOR';
  if (!msg) return;
  if (!apiKeyEl) {
    toast('API key field not found — please hard-refresh the page (Cmd+Shift+R)', 'error');
    return;
  }
  if (!apiKey) { toast('Enter your Anthropic API key in the top bar first', 'error'); return; }

  appendMsg('user', msg);
  input.value = '';
  state.chatHistory.push({ role: 'user', content: msg });

  const typingId = appendMsg('bot', '…');

  try {
    const payload = {
      message:       msg,
      api_key:       apiKey,
      mode,
      history:       state.chatHistory.slice(0,-1),
      model_context: buildModelContext(),   // inject live AHP results
    };
    const r    = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    const reply  = data.reply;
    const parsed = parseBotResponse(reply);
    const msgEl  = document.getElementById(typingId);
    if (msgEl && parsed) {
      // Build card skeleton — insight empty, question hidden
      msgEl.innerHTML = `
        <div class="msg-avatar-ai">AI</div>
        <div class="msg-card">
          <div class="msg-insight" id="${typingId}-insight"></div>
          <div class="msg-question" id="${typingId}-q" style="opacity:0;transition:opacity .4s">
            <span class="msg-q-icon">?</span>
            <span class="msg-q-text">${escHtml(parsed.question)}</span>
          </div>
        </div>`;
      // Typewriter the insight
      const insightEl = document.getElementById(typingId + '-insight');
      const words = parsed.insight.split(' ');
      let revealed = '';
      for (let i = 0; i < words.length; i++) {
        revealed += (i > 0 ? ' ' : '') + words[i];
        insightEl.textContent = revealed;
        document.getElementById('chatArea').scrollTop = 9999;
        await new Promise(r => setTimeout(r, 22));
      }
      // Fade in the question card
      await new Promise(r => setTimeout(r, 180));
      const qEl = document.getElementById(typingId + '-q');
      if (qEl) qEl.style.opacity = '1';
    } else if (msgEl) {
      // Fallback: plain typewriter
      const words = reply.split(' ');
      let revealed = '';
      const bubble = msgEl.querySelector('.msg-bubble') || msgEl;
      for (let i = 0; i < words.length; i++) {
        revealed += (i > 0 ? ' ' : '') + words[i];
        bubble.innerHTML = revealed.replace(/\n/g,'<br>');
        document.getElementById('chatArea').scrollTop = 9999;
        await new Promise(r => setTimeout(r, 18));
      }
    }
    state.chatHistory.push({ role: 'assistant', content: data.reply });
  } catch(e) {
    updateMsg(typingId, '⚠ Error: ' + e.message);
    toast(e.message, 'error');
  }
}

function clearChat() {
  document.getElementById('chatArea').innerHTML = `
    <div class="msg bot">
      <div class="msg-avatar-ai">AI</div>
      <div class="msg-card">
        <div class="msg-insight">Ready for your questions. Run the model first (▶ Run Model), then ask me anything.</div>
        <div class="msg-question">
          <span class="msg-q-icon">?</span>
          <span class="msg-q-text">What's the single biggest risk in your current allocation?</span>
        </div>
      </div>
    </div>`;
  state.chatHistory = [];
}

function resetAdvisor() {
  // Reset mode selector to ADVISOR, clear chat, clear input
  const modeEl = document.getElementById('chatMode');
  if (modeEl) {
    modeEl.value = 'ADVISOR';
    document.getElementById('modeDesc').textContent = modeDescs['ADVISOR'];
  }
  document.getElementById('chatInput').value = '';
  clearChat();
  toast('AI Advisor reset to default', 'success');
}

let msgCounter = 0;

function parseBotResponse(text) {
  // Parse INSIGHT: ... QUESTION: ... format
  const iMatch = text.match(/INSIGHT:\s*([\s\S]+?)(?=\nQUESTION:|$)/i);
  const qMatch = text.match(/QUESTION:\s*([\s\S]+?)$/i);
  if (iMatch && qMatch) {
    return { insight: iMatch[1].trim(), question: qMatch[1].trim() };
  }
  return null;
}

function buildBotHTML(text, isTyping) {
  if (isTyping) {
    return `<div class="msg-avatar-ai">AI</div><div class="msg-bubble msg-typing">…</div>`;
  }
  const parsed = parseBotResponse(text);
  if (parsed) {
    return `
      <div class="msg-avatar-ai">AI</div>
      <div class="msg-card">
        <div class="msg-insight">${escHtml(parsed.insight)}</div>
        <div class="msg-question">
          <span class="msg-q-icon">?</span>
          <span class="msg-q-text">${escHtml(parsed.question)}</span>
        </div>
      </div>`;
  }
  // Fallback: plain text
  let html = escHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
  return `<div class="msg-avatar-ai">AI</div><div class="msg-bubble">${html}</div>`;
}

function appendMsg(role, text) {
  const id   = 'msg-' + (++msgCounter);
  const area = document.getElementById('chatArea');
  const div  = document.createElement('div');
  div.className = 'msg ' + role;
  div.id = id;
  if (role === 'user') {
    div.innerHTML = `<div class="msg-avatar">U</div><div class="msg-bubble">${escHtml(text)}</div>`;
  } else {
    div.innerHTML = buildBotHTML(text, text === '…');
  }
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return id;
}

function updateMsg(id, text) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.classList.contains('bot')) {
    el.innerHTML = buildBotHTML(text, false);
  } else {
    el.querySelector('.msg-bubble').textContent = text;
  }
  document.getElementById('chatArea').scrollTop = 9999;
}

// ── AHP HIERARCHY RENDERER ────────────────────────────────
// ── SUB-CRITERIA DEEP DIVE DATA ───────────────────────────
const SUB_CRIT_DATA = {
  return: [
    {
      id: 'expected_return', label: 'Expected Return (E[R])', icon: '📈',
      plain: 'The annualised total return forecast for each asset class.',
      detail: 'Derived from 5-year historical price data. Large Stocks average ~12%/yr vs Government Bonds at −0.9%. This sub-criterion carries the most weight in the Return score — assets with high expected return get a strong boost in AHP ranking. Computed as: (ending price / beginning price)^(1/years) − 1.',
      pensionNote: 'A pension fund needs roughly 6–8% total portfolio return to remain fully funded over the long run. Any asset below this hurdle must justify its allocation via risk reduction or diversification.',
      liveKey: 'expected_return', unit: '%', weight: '~45% of Return score', better: 'higher', format: v => v?.toFixed(1) + '%',
    },
    {
      id: 'dividend_yield', label: 'Dividend / Income Yield', icon: '💰',
      plain: 'Annual cash income paid out as a % of asset price.',
      detail: 'Represents the income component of total return. Pension funds with monthly benefit obligations prefer assets generating regular cash flows — this reduces the need to sell holdings to fund payouts. High dividend yield assets include REITs (VNQ), bonds (LQD/IEF), and mature large-cap equities.',
      pensionNote: 'Funds with near-term liabilities (high payout years) should overweight high dividend yield to generate predictable cash without forced selling during downturns.',
      liveKey: 'dividend_yield', unit: '%', weight: '~25% of Return score', better: 'higher', format: v => v?.toFixed(1) + '%',
    },
    {
      id: 'growth_potential', label: 'Growth Potential', icon: '🚀',
      plain: 'Long-run capital appreciation capacity of the asset.',
      detail: 'Real assets (equities, real estate, commodities) score highest; money market instruments score near zero. Growth potential matters most for long-horizon funds that can tolerate short-run volatility in exchange for higher terminal wealth. Measured qualitatively using analyst consensus and historical real return premium.',
      pensionNote: 'Young pension funds (far from payout peak) should maximise growth potential. Mature funds approaching full payout should shift toward income and capital preservation.',
      liveKey: null, unit: '', weight: '~15% of Return score', better: 'higher', format: () => 'qualitative',
    },
    {
      id: 'sharpe_ratio', label: 'Risk-Adjusted Return (Sharpe)', icon: '⚡',
      plain: 'How much return you earn per unit of risk taken.',
      detail: 'Sharpe Ratio = (Return − Risk-Free Rate) / Volatility. A higher Sharpe means more return for each unit of risk. Large Stocks historically achieve Sharpe ~0.7–0.9 in bull markets; Money Market achieves ~0.2 but with near-zero risk. AHP uses this to balance raw return expectations against risk-taking.',
      pensionNote: 'Pension funds should target a portfolio Sharpe Ratio above 0.5. Assets with negative Sharpe (return below risk-free rate) destroy risk-adjusted value and should be limited unless required for diversification.',
      liveKey: 'sharpe', unit: '', weight: '~10% of Return score', better: 'higher', format: v => v?.toFixed(2),
    },
  ],
  risk: [
    {
      id: 'beta', label: 'Market Beta (β)', icon: '📊',
      plain: 'How much the asset moves when the stock market moves.',
      detail: 'Beta = 1.0 means the asset mirrors the market exactly. β > 1 amplifies market swings (Small Stocks β=1.11). β < 1 dampens them (Money Market β=0.01, Government Bonds β=0.28). AHP treats lower beta as safer — a pension fund with a fragile funded ratio needs assets that won\'t fall 30% in a crash. Systematic risk that cannot be diversified away.',
      pensionNote: 'A well-funded fund (>100%) can tolerate β>1. An underfunded fund (<80% funded ratio) should keep average portfolio beta below 0.6 to limit drawdown risk during equity corrections.',
      liveKey: 'beta', unit: '', weight: '~25% of Risk score', better: 'lower', format: v => v?.toFixed(2),
    },
    {
      id: 'volatility', label: 'Total Volatility (σ)', icon: '🌊',
      plain: 'How unpredictably an asset\'s price bounces up and down.',
      detail: 'Annualised standard deviation of monthly returns. Small Stocks σ=20.7% vs Money Market σ=1.0%. Volatility captures BOTH systematic and unsystematic risk. High volatility makes it hard to predict portfolio value next year — a critical problem when you have fixed benefit obligations. The AHP model penalises high-volatility assets strongly on the Risk criterion.',
      pensionNote: 'Every 1% increase in portfolio volatility adds roughly 0.5% to annual Value-at-Risk. A funded ratio of 87% with 15% portfolio vol means there\'s a real probability of dipping below 80% in a bad year, triggering regulatory contribution calls.',
      liveKey: 'volatility', unit: '%', weight: '~25% of Risk score', better: 'lower', format: v => v?.toFixed(1) + '%',
    },
    {
      id: 'max_drawdown', label: 'Maximum Drawdown', icon: '📉',
      plain: 'The worst peak-to-trough loss over the past 5 years — the actual worst case you experienced.',
      detail: 'If an asset was worth $100 at peak and fell to $67, max drawdown = −33%. Real Estate hit −32.1% in this period; Money Market only −0.1%. This is the "sleep at night" metric — it tells you the worst you would have experienced in a real market crisis. AHP weights this heavily because large drawdowns in pension funds trigger regulatory contribution calls and can permanently impair the fund.',
      pensionNote: 'A 20%+ portfolio drawdown with 85% funded ratio could push the fund below the 80% regulatory threshold, forcing emergency employer contributions — a significant reputational and financial risk for both sponsor and beneficiaries.',
      liveKey: 'max_drawdown', unit: '%', weight: '~25% of Risk score', better: 'higher (less negative)', format: v => v?.toFixed(1) + '%',
    },
    {
      id: 'liquidity_risk', label: 'Liquidity Risk', icon: '🔒',
      plain: 'How hard and expensive it is to sell the asset quickly without losing money.',
      detail: 'A large-cap stock can be sold in seconds at the listed price. A real estate holding might take 6–12 months to exit, requiring a 10–20% discount for forced sale. In a crisis, illiquid assets can gap down 30–50% before a buyer appears. The model scores this via the Liquidity Score (0–1 scale, higher = more liquid). Distinct from the Liquidity criterion — this measures the RISK of being unable to exit, not the ease of day-to-day trading.',
      pensionNote: 'Pension funds must maintain enough liquid assets to cover at least 12 months of benefit payments. When illiquid holdings exceed ~30% of AUM, a sudden market stress can create a genuine liquidity crunch — the fund may have to sell its best assets first (fire sale).',
      liveKey: 'liquidity', unit: '/1.0', weight: '~15% of Risk score', better: 'higher', format: v => v?.toFixed(2),
    },
    {
      id: 'tail_risk', label: 'Tail Risk / CVaR', icon: '☠️',
      plain: 'The expected loss in the worst 5% of scenarios — beyond what normal volatility predicts.',
      detail: 'Conditional Value at Risk (CVaR) at 95% confidence asks: "In the worst 5% of months, how bad was it?" This captures fat-tail events that standard volatility misses. Small Stocks and Real Estate have significant left-tail fat tails; Government Bonds have thin left tails. Essential for pension funds because a tail event can permanently impair funding levels.',
      pensionNote: 'Actuarial stress tests require CVaR analysis. The 2008 GFC showed that many "safe" assets had hidden fat tails — correlation spiked to 0.9+ across asset classes precisely when diversification was most needed.',
      liveKey: null, unit: '', weight: '~5% of Risk score', better: 'lower', format: () => 'not in live data',
    },
    {
      id: 'duration_risk', label: 'Duration / Interest Rate Risk', icon: '⏱️',
      plain: 'How much the asset price changes when interest rates move.',
      detail: 'Duration measures the sensitivity of a fixed-income asset\'s price to interest rate changes. A bond with duration 7 loses ~7% in value for every 1% rise in rates. Government Bonds (IEF) have duration ~7.5 years; Corporate Bonds (LQD) ~8.5 years; equities have much lower interest rate sensitivity. Critical in rising rate environments like 2022.',
      pensionNote: 'Pension liabilities also have a duration (typically 10–20 years for mature plans). Immunisation strategies match asset and liability duration to minimise funded ratio volatility. An unhedged pension fund lost 15–20% of its funded ratio in 2022 as rates rose 425bps.',
      liveKey: null, unit: 'years', weight: '~5% of Risk score', better: 'lower for risk', format: () => 'qualitative',
    },
  ],
  liquidity: [
    {
      id: 'trading_volume', label: 'Daily Trading Volume', icon: '📦',
      plain: 'How many dollars worth of the asset trade hands each day.',
      detail: 'A pension fund allocating $400M to Small Stocks (IWM) needs to be able to execute without moving the market. IWM trades ~$3B daily — a $400M position can be liquidated in 1–2 days without significant market impact. A less liquid asset trading $10M/day would take weeks to exit and would move the price against you.',
      pensionNote: 'A rule of thumb: a fund should hold no more than 5–10% of an asset\'s average daily trading volume in any single position. Exceeding this creates "market impact" — you become the market when you try to sell.',
      liveKey: 'liquidity', unit: '/1.0', weight: '~35% of Liquidity score', better: 'higher', format: v => v?.toFixed(2),
    },
    {
      id: 'bid_ask_spread', label: 'Bid-Ask Spread', icon: '↔️',
      plain: 'The cost of immediately buying and then selling an asset — the market\'s fee for liquidity.',
      detail: 'The bid-ask spread is the gap between what buyers will pay and sellers will accept. Large-cap ETFs like SPY have spreads of 0.01% — nearly zero. Emerging market bonds might have spreads of 0.5–2%. Real estate has effective spreads of 5–10% (agent fees, transfer taxes). This is a real cost every time a pension fund rebalances.',
      pensionNote: 'A fund rebalancing a $3.2B portfolio quarterly with average 0.1% spread pays roughly $3.2M in implicit transaction costs per year just from bid-ask. Minimising spread costs is why large funds prefer large liquid ETFs over individual securities.',
      liveKey: null, unit: '', weight: '~25% of Liquidity score', better: 'lower', format: () => 'qualitative',
    },
    {
      id: 'settlement_time', label: 'Settlement & Exit Time', icon: '⏳',
      plain: 'How long it takes to actually receive cash after deciding to sell.',
      detail: 'US equities settle T+1 (cash in hand next business day). Government bonds settle T+1. Corporate bonds T+2. Real estate can take 30–90 days to close a deal, and finding a buyer at fair value in a distressed market may take 6–12 months. Private equity and hedge funds may have lock-up periods of 3–10 years.',
      pensionNote: 'A fund must know its liquidity runway — if it needs to pay $100M in benefits next month, it needs at least $100M in T+2 or faster assets today. Holding too much in T+30 or longer assets creates refinancing risk.',
      liveKey: null, unit: '', weight: '~25% of Liquidity score', better: 'lower', format: () => 'qualitative',
    },
    {
      id: 'market_depth', label: 'Market Depth', icon: '🏊',
      plain: 'How large an order the market can absorb without significantly moving the price.',
      detail: 'A deep market has many buyers and sellers at multiple price levels. SPY (S&P 500 ETF) has hundreds of millions of dollars of resting orders within 0.01% of the mid-price. A thin market might have only $50K of depth — even a modest $5M sell order would gap the price down 5%. Commodities and real estate are notoriously thin in crisis periods.',
      pensionNote: 'For a $3.2B pension fund, market depth is critical. Trying to liquidate $320M of a single asset class in a risk-off event could trigger a cascade — selling pressure from one large fund alerts other participants, who also rush to sell.',
      liveKey: 'liquidity', unit: '/1.0', weight: '~15% of Liquidity score', better: 'higher', format: v => v?.toFixed(2),
    },
  ],
  diversification: [
    {
      id: 'avg_correlation', label: 'Portfolio Correlation (ρ̄)', icon: '🔗',
      plain: 'How much the asset moves in sync with the rest of the portfolio.',
      detail: 'Average pairwise correlation with the other 6 asset classes. An asset with ρ=0.8 tends to rise and fall together with the existing portfolio — adding it provides little protection in a crash. An asset with ρ=0.1 or negative correlation provides genuine diversification benefit — it zigs when everything else zags. Commodities and Government Bonds tend to have low or negative correlation with equities.',
      pensionNote: 'Modern Portfolio Theory shows that combining assets with low correlation reduces portfolio volatility without sacrificing expected return. A pension fund can "earn" diversification — getting the same return with less risk, or more return with the same risk.',
      liveKey: 'avg_correlation', unit: '', weight: '~45% of Diversification score', better: 'lower', format: v => v?.toFixed(2),
    },
    {
      id: 'factor_exposure', label: 'Factor Exposure', icon: '🧩',
      plain: 'Which systematic risk factors (Value, Momentum, Quality, Size) drive the asset\'s returns.',
      detail: 'Factor models decompose returns into systematic components: Market (beta), Size (small vs large), Value (cheap vs expensive), Momentum (trending), Quality (profitable vs unprofitable), Low Volatility. An asset with high unique factor exposure adds diversification to a portfolio that is already heavily exposed to another factor. Commodities add inflation-factor exposure that most equity-heavy funds lack.',
      pensionNote: 'CalPERS and APG explicitly allocate to factor premia (value, momentum, low vol). A fund over-concentrated in the Market factor (high-beta stocks) is not truly diversified — it just owns the same risk with more names.',
      liveKey: null, unit: '', weight: '~30% of Diversification score', better: 'low overlap', format: () => 'qualitative',
    },
    {
      id: 'geographic_exposure', label: 'Geographic Diversification', icon: '🌍',
      plain: 'How much of the asset\'s return comes from non-US economic activity.',
      detail: 'US equities are ~60% correlated with US GDP. International bonds and commodities have significant non-US exposure. Geographically diversified assets protect against a US-specific recession or policy shock. CalPERS holds ~25% in international equity specifically for geographic diversification. A purely domestic portfolio is exposed to US political and regulatory risk.',
      pensionNote: 'US pension funds with purely domestic portfolios are exposed to a single regulatory regime, a single central bank, and a single economic cycle. Global diversification is especially valuable for funds with liabilities extending 30–40 years.',
      liveKey: null, unit: '', weight: '~15% of Diversification score', better: 'higher non-US', format: () => 'qualitative',
    },
    {
      id: 'concentration_risk', label: 'Concentration Risk', icon: '🎯',
      plain: 'Whether the asset is dominated by a few large holdings or positions.',
      detail: 'SPY tracks 500 stocks with no single holding above 7%. Real Estate (VNQ) is more concentrated — the top 10 REITs represent 40%+ of the fund. Concentration risk means idiosyncratic events (a single company\'s bankruptcy, a single sector\'s collapse) can disproportionately impact the asset class. Low concentration = better diversification within the asset class itself.',
      pensionNote: 'Pension fund trustees require position limit policies. No single security should represent more than 5% of the fund. An asset class dominated by a handful of names effectively violates this spirit even if individual positions are small.',
      liveKey: null, unit: '', weight: '~10% of Diversification score', better: 'lower', format: () => 'qualitative',
    },
  ],
};

function switchSubCritTab(group, btn) {
  document.querySelectorAll('.subcrit-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  renderSubCritCards(group);
}

function renderSubCritCards(group) {
  const container = document.getElementById('subCritCards');
  if (!container) return;
  const items = SUB_CRIT_DATA[group] || [];
  const ev = state.evidence || {};
  const assetKeys = Object.keys(ev);

  container.innerHTML = `<div class="subcrit-cards-grid">${items.map(item => {
    let topAsset = '', topVal = '', bottomAsset = '', bottomVal = '';
    if (item.liveKey && assetKeys.length) {
      const withData = assetKeys.filter(a => ev[a]?.[item.liveKey] != null);
      if (withData.length) {
        const sorted = [...withData].sort((a, b) => {
          const va = ev[a][item.liveKey], vb = ev[b][item.liveKey];
          return item.better === 'lower' ? va - vb : vb - va;
        });
        topAsset    = sorted[0];
        topVal      = item.format(ev[topAsset]?.[item.liveKey]);
        bottomAsset = sorted[sorted.length - 1];
        bottomVal   = item.format(ev[bottomAsset]?.[item.liveKey]);
      }
    }
    const assetsHtml = (topAsset && bottomAsset && topAsset !== bottomAsset) ? `
      <div class="subcrit-card-assets">
        <span class="subcrit-best">✓ Best: ${topAsset} (${topVal})</span>
        <span class="subcrit-worst">✗ Highest risk: ${bottomAsset} (${bottomVal})</span>
      </div>` : '';

    return `<div class="subcrit-card">
      <div class="subcrit-card-header">
        <span class="subcrit-card-icon">${item.icon}</span>
        <div>
          <div class="subcrit-card-title">${item.label}</div>
          <span class="subcrit-card-weight">${item.weight}</span>
        </div>
      </div>
      <div class="subcrit-card-plain">${item.plain}</div>
      <div class="subcrit-card-detail">${item.detail}</div>
      ${assetsHtml}
      <div class="subcrit-card-pension">💡 ${item.pensionNote}</div>
    </div>`;
  }).join('')}</div>`;
}

const HIERARCHY_DATA = {
  goal: { label: 'Optimal Portfolio Allocation', type: 'goal', desc: 'The overarching objective: determine the best long-run allocation of pension fund assets to meet liability obligations while maximising risk-adjusted return.' },
  actors: [
    { label: 'Sponsor',           type: 'actor', desc: 'The pension fund sponsor defines overall investment policy constraints and funded ratio targets. Their preferences set the strategic boundary conditions.' },
    { label: 'Beneficiaries',     type: 'actor', desc: 'Future retirees whose income security depends on fund performance and liability matching. Beneficiary risk aversion heavily constrains downside tolerance.' },
    { label: 'Portfolio Manager', type: 'actor', desc: 'Executes allocation decisions within policy bands, optimises for risk-adjusted return, and manages tactical deviations from the strategic benchmark.' },
  ],
  horizons: [
    { label: 'Short-term',  type: 'horizon', desc: 'Planning window of 1–3 years. Emphasises liquidity and capital preservation. Suitable for de-risking phases or near-term liability matching.' },
    { label: 'Medium-term', type: 'horizon', desc: 'Planning window of 3–7 years. Balances growth with risk control. Most common for funds targeting full funding within a decade.' },
    { label: 'Long-term',   type: 'horizon', desc: 'Planning window of 7+ years. Emphasises return maximisation and diversification. Allows illiquidity premia from real assets and private markets.' },
  ],
  scenarios: [
    { label: 'Bull Market',   type: 'scenario', desc: 'Strong economic expansion with rising equity markets. Historically associated with above-average equity returns and compressed credit spreads.' },
    { label: 'Stagflation',   type: 'scenario', desc: 'Low growth combined with high inflation. Historically unfavourable for bonds; real assets, commodities, and inflation-linked instruments outperform.' },
    { label: 'Deflation',     type: 'scenario', desc: 'Falling price levels with contracting economic activity. Government bonds typically provide safe-haven returns; equities and real estate underperform.' },
    { label: 'Steady Growth', type: 'scenario', desc: 'Moderate GDP growth, stable inflation near 2%, positive but not exuberant equity markets. The baseline calibration scenario for the Liberty Bell model.' },
  ],
  criteria: [
    {
      label: 'Return', type: 'criterion',
      desc: 'Weights expected returns, dividend yield, growth potential, risk-adjusted return and inflation sensitivity across asset classes. Single largest criterion by AHP weight (approx 40%).',
      approxWeight: 0.40,
      subCriteria: [
        { label: 'Expected Return',  type: 'sub-criterion', dataKey: 'return', desc: 'Annualised total return expectation derived from historical data and forward-looking economic models. Large Stocks avg ~12%/yr; Govt Bonds avg −0.9% in recent data.', weight: '~45%' },
        { label: 'Dividend Yield',   type: 'sub-criterion', dataKey: 'return', desc: 'Current income component. Particularly relevant for liability-matching strategies requiring regular cash flows. REITs and bonds score highest.', weight: '~25%' },
        { label: 'Growth Potential', type: 'sub-criterion', dataKey: 'return', desc: 'Long-run capital appreciation capacity. Higher for equities and real estate; lower for fixed income. Qualitative score based on analyst consensus.', weight: '~15%' },
        { label: 'Sharpe Ratio',     type: 'sub-criterion', dataKey: 'return', desc: 'Risk-adjusted return: (Return − Risk-Free) / Volatility. A Sharpe > 0.5 is the pension fund target. Assets with negative Sharpe destroy risk-adjusted value.', weight: '~10%' },
        { label: 'Inflation Beta',   type: 'sub-criterion', dataKey: 'return', desc: 'Measures how asset returns co-move with CPI. Commodities and real estate have positive inflation beta — critical for CPI-linked pension liabilities.', weight: '~5%' },
      ]
    },
    {
      label: 'Risk', type: 'criterion',
      desc: 'Captures beta, volatility, maximum drawdown, liquidity risk, CVaR, and duration risk for each asset. Second largest criterion (approx 35%).',
      approxWeight: 0.35,
      subCriteria: [
        { label: 'Market Beta',    type: 'sub-criterion', dataKey: 'risk', desc: 'Systematic market risk (β). β=1 mirrors market; β<1 dampens swings. Underfunded plans (< 80% ratio) should keep portfolio β below 0.6 to limit drawdown.', weight: '~25%' },
        { label: 'Volatility',     type: 'sub-criterion', dataKey: 'risk', desc: 'Annualised standard deviation of returns. Small Stocks σ=20.7% vs Money Market σ=1.0%. Each 1% rise in portfolio vol adds ~0.5% to annual VaR.', weight: '~25%' },
        { label: 'Max Drawdown',   type: 'sub-criterion', dataKey: 'risk', desc: 'Peak-to-trough decline over 5-year window. Real Estate hit −32.1%; Money Market only −0.1%. A 20%+ drawdown can push a fund below the 80% regulatory threshold.', weight: '~25%' },
        { label: 'Liquidity Risk', type: 'sub-criterion', dataKey: 'risk', desc: 'Risk of inability to exit at fair value. Real estate may take 6–12 months to sell at full value. Illiquid holdings > 30% of AUM can cause genuine crises.', weight: '~15%' },
        { label: 'Tail Risk (CVaR)', type: 'sub-criterion', dataKey: 'risk', desc: 'Conditional Value at Risk at 95% confidence — expected loss in the worst 5% of scenarios. Captures fat-tail events that standard vol misses. Essential for stress testing.', weight: '~5%' },
        { label: 'Duration Risk',  type: 'sub-criterion', dataKey: 'risk', desc: 'Interest rate sensitivity of fixed-income assets. IEF duration ≈7.5 yrs; LQD ≈8.5 yrs. In 2022, unhedged plans lost 15–20% of funded ratio as rates rose 425bps.', weight: '~5%' },
      ]
    },
    {
      label: 'Liquidity', type: 'criterion',
      desc: 'Measures ability to convert positions to cash without significant price impact. Important for pension funds with ongoing benefit payments (approx 15%).',
      approxWeight: 0.15,
      subCriteria: [
        { label: 'Daily Volume',      type: 'sub-criterion', dataKey: 'liquidity', desc: 'Dollars traded daily. IWM trades ~$3B/day — a $400M position can be liquidated in 1–2 days without market impact. Rule: hold ≤5–10% of avg daily volume.', weight: '~35%' },
        { label: 'Bid-Ask Spread',    type: 'sub-criterion', dataKey: 'liquidity', desc: 'Cost of immediately buying and selling. SPY spread ≈0.01%; real estate effective spread ≈5–10%. A $3.2B portfolio with 0.1% spread pays $3.2M/yr in implicit costs.', weight: '~25%' },
        { label: 'Settlement Time',   type: 'sub-criterion', dataKey: 'liquidity', desc: 'US equities settle T+1; real estate 30–90 days. A fund must hold enough T+2 or faster assets to cover 12+ months of benefit payments at all times.', weight: '~25%' },
        { label: 'Market Depth',      type: 'sub-criterion', dataKey: 'liquidity', desc: 'How large an order the market can absorb. SPY has $100M+ depth within 0.01% of mid. Thin markets (commodities, small-cap real estate) gap down when large orders hit.', weight: '~15%' },
      ]
    },
    {
      label: 'Diversification', type: 'criterion',
      desc: 'Penalises high correlation with existing portfolio. Rewards assets that provide independent return streams, reducing overall portfolio variance (approx 10%).',
      approxWeight: 0.10,
      subCriteria: [
        { label: 'Avg Correlation',     type: 'sub-criterion', dataKey: 'diversification', desc: 'Average pairwise correlation with other 6 asset classes. Low ρ = genuine diversification. Commodities and Govt Bonds have low/negative correlation with equities.', weight: '~45%' },
        { label: 'Factor Exposure',     type: 'sub-criterion', dataKey: 'diversification', desc: 'Which systematic factors (Value, Momentum, Quality, Size) drive returns. Unique factor exposure adds diversification beyond simple correlation analysis. Commodities add inflation-factor exposure.', weight: '~30%' },
        { label: 'Geographic Spread',   type: 'sub-criterion', dataKey: 'diversification', desc: 'Non-US economic exposure. US equities are ~60% correlated with US GDP. International assets protect against US-specific shocks. CalPERS holds ~25% in international equity.', weight: '~15%' },
        { label: 'Concentration Risk',  type: 'sub-criterion', dataKey: 'diversification', desc: 'Whether the asset class is dominated by a few holdings. SPY = 500 stocks (top 10 < 30%); VNQ top 10 REITs = 40%+. Higher concentration = idiosyncratic risk leaks in.', weight: '~10%' },
      ]
    },
  ],
  assets: [
    { label: 'Small Stocks',  type: 'asset', desc: 'IWM proxy. High growth potential and elevated volatility. Historically outperforms in early-cycle recoveries. Policy band: 5–25%.' },
    { label: 'Large Stocks',  type: 'asset', desc: 'SPY proxy. Core equity exposure with dividend income. Balances growth and stability. Policy band: 10–35%.' },
    { label: 'Corp Bonds',    type: 'asset', desc: 'LQD proxy. Investment-grade corporate debt. Income stream with credit risk premium over Treasuries. Policy band: 5–25%.' },
    { label: 'Govt Bonds',    type: 'asset', desc: 'IEF proxy. Sovereign fixed income. Safe-haven asset for deflation/risk-off scenarios. Liability-matching instrument. Policy band: 10–30%.' },
    { label: 'Real Estate',   type: 'asset', desc: 'VNQ proxy. Inflation hedge with illiquidity premium. Provides income and capital appreciation. Policy band: 5–20%.' },
    { label: 'Money Market',  type: 'asset', desc: 'BIL proxy. Short-duration cash equivalent. Maximum liquidity; used for tactical dry powder and near-term liability reserves. Policy band: 2–15%.' },
    { label: 'Commodities',   type: 'asset', desc: 'GSG proxy. Real asset diversifier and inflation hedge. Uncorrelated with financial assets in stagflation scenarios. Policy band: 2–12%.' },
  ],
};

function renderHierarchy() {
  const container = document.getElementById('hierarchyTree');
  if (!container) return;

  // Simple levels (no sub-criteria)
  const simpleLevels = [
    { label: 'L1 · Goal',      nodes: [HIERARCHY_DATA.goal],     li: 0 },
    { label: 'L2 · Actors',    nodes: HIERARCHY_DATA.actors,     li: 1 },
    { label: 'L3 · Horizon',   nodes: HIERARCHY_DATA.horizons,   li: 2 },
    { label: 'L4 · Scenarios', nodes: HIERARCHY_DATA.scenarios,  li: 3 },
  ];

  let html = '';

  // Render L1–L4
  simpleLevels.forEach(({ label, nodes, li }) => {
    html += `<div class="h-level" id="h-level-${li}">`;
    html += `<div class="h-level-label">${label}</div>`;
    html += `<div class="h-nodes">`;
    nodes.forEach((node, ni) => {
      const nodeId = `hnode-${li}-${ni}`;
      html += `<span class="h-node ${node.type}" id="${nodeId}" onclick="selectHNode('${nodeId}',${li},${ni})">${node.label}</span>`;
    });
    html += `</div></div>`;
    html += `<div class="h-detail-panel" id="h-detail-${li}"></div>`;
  });

  // L5 — Criteria + Sub-criteria (special layout)
  const li5 = 4;
  html += `<div class="h-level h-level-criteria" id="h-level-${li5}">`;
  html += `<div class="h-level-label">L5 · Criteria<br><span style="font-size:.6rem;opacity:.6;font-weight:400">+ sub-criteria</span></div>`;
  html += `<div class="h-nodes">`;

  // Row 1: the 4 main criteria pills
  html += `<div class="h-criteria-row">`;
  HIERARCHY_DATA.criteria.forEach((node, ni) => {
    const nodeId = `hnode-${li5}-${ni}`;
    const arrow = node.subCriteria.length ? ' <span style="opacity:.5;font-size:.65rem">▾</span>' : '';
    html += `<span class="h-node criterion" id="${nodeId}" onclick="selectHNode('${nodeId}',${li5},${ni})">${node.label}${arrow}</span>`;
  });
  html += `</div>`;

  // Row 2: sub-criteria grouped under their parent criterion
  html += `<div class="h-subcrit-groups">`;
  HIERARCHY_DATA.criteria.forEach((node, ni) => {
    if (!node.subCriteria.length) return;
    html += `<div class="h-sub-group">`;
    html += `<div class="h-sub-header">${node.label}</div>`;
    html += `<div class="h-sub-nodes">`;
    node.subCriteria.forEach((sc, sci) => {
      const scId = `hnode-${li5}-${ni}-sub-${sci}`;
      html += `<span class="h-node sub-criterion" id="${scId}" onclick="selectHSubNode('${scId}',${li5},${ni},${sci})">${sc.label}</span>`;
    });
    html += `</div></div>`;
  });
  html += `</div>`;

  html += `</div></div>`;
  html += `<div class="h-detail-panel" id="h-detail-${li5}"></div>`;

  // L6 — Asset classes
  const li6 = 5;
  html += `<div class="h-level" id="h-level-${li6}">`;
  html += `<div class="h-level-label">L6 · Assets</div>`;
  html += `<div class="h-nodes">`;
  HIERARCHY_DATA.assets.forEach((node, ni) => {
    const nodeId = `hnode-${li6}-${ni}`;
    html += `<span class="h-node asset" id="${nodeId}" onclick="selectHNode('${nodeId}',${li6},${ni})">${node.label}</span>`;
  });
  html += `</div></div>`;
  html += `<div class="h-detail-panel" id="h-detail-${li6}"></div>`;

  container.innerHTML = html;
}

function selectHNode(nodeId, levelIdx, nodeIdx) {
  document.querySelectorAll(`#h-level-${levelIdx} .h-node`).forEach(n => n.classList.remove('active'));
  const el = document.getElementById(nodeId);
  if (el) el.classList.add('active');

  const levelNodes = [
    [HIERARCHY_DATA.goal],
    HIERARCHY_DATA.actors,
    HIERARCHY_DATA.horizons,
    HIERARCHY_DATA.scenarios,
    HIERARCHY_DATA.criteria,
    HIERARCHY_DATA.assets,
  ][levelIdx];
  const node = levelNodes?.[nodeIdx];
  if (!node) return;

  const panel = document.getElementById(`h-detail-${levelIdx}`);
  if (!panel) return;

  let html = '';

  // ── GOAL NODE ──
  if (node.type === 'goal') {
    const grade  = state.result?.overall_grade || '—';
    const topW   = state.result ? Object.entries(state.result.constrained_weights||{}).sort((a,b)=>b[1]-a[1]) : [];
    const topAsset = topW[0] ? topW[0][0] + ' (' + pct(topW[0][1]) + ')' : 'Run model first';
    html = `<div class="h-rich-panel">
      <div class="h-rich-title">🎯 ${node.label}</div>
      <div class="h-rich-desc">${node.desc}</div>
      <div class="h-rich-stats">
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--green)">${grade}</div><div class="h-rich-stat-lbl">AHP Grade</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--accent2)">${topAsset}</div><div class="h-rich-stat-lbl">Top Allocation</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--text)">6 Levels</div><div class="h-rich-stat-lbl">Hierarchy Depth</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--text)">7 Assets</div><div class="h-rich-stat-lbl">Alternatives</div></div>
      </div>
      <div class="h-rich-note">💡 The Goal level anchors all pairwise comparisons — every Saaty judgment flows upward toward this single objective: maximise risk-adjusted return within policy constraints for a pension fund under defined liabilities.</div>
    </div>`;
  }

  // ── ACTOR NODES ──
  else if (node.type === 'actor') {
    const actorWeights = { 'Sponsor': '30%', 'Beneficiaries': '30%', 'Portfolio Manager': '40%' };
    const actorEmphasis = {
      'Sponsor': 'Funded ratio, contribution minimisation, liability horizon',
      'Beneficiaries': 'Income security, inflation protection, downside risk',
      'Portfolio Manager': 'Risk-adjusted return, Sharpe ratio, tracking error vs benchmark',
    };
    html = `<div class="h-rich-panel">
      <div class="h-rich-title">👤 Actor: ${node.label}</div>
      <div class="h-rich-desc">${node.desc}</div>
      <div class="h-rich-stats">
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--yellow)">${actorWeights[node.label] || '33%'}</div><div class="h-rich-stat-lbl">Influence Weight</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--accent2);font-size:.72rem">${actorEmphasis[node.label] || 'Balanced'}</div><div class="h-rich-stat-lbl">Primary Emphasis</div></div>
      </div>
      <div class="h-rich-note">💡 AHP aggregates all three actors' preferences via weighted geometric mean of their individual pairwise judgments. The model is currently calibrated using the Portfolio Manager's perspective as the primary weighting actor.</div>
    </div>`;
  }

  // ── HORIZON NODES ──
  else if (node.type === 'horizon') {
    const horizonAssets = {
      'Short-term':  'Money Market, Govt Bonds — preserve capital, maintain liquidity reserves',
      'Medium-term': 'Corp Bonds, Large Stocks, Govt Bonds — balance growth with liability matching',
      'Long-term':   'Small Stocks, Large Stocks, Real Estate, Commodities — maximise long-run compound growth',
    };
    html = `<div class="h-rich-panel">
      <div class="h-rich-title">⏱ Horizon: ${node.label}</div>
      <div class="h-rich-desc">${node.desc}</div>
      <div class="h-rich-note" style="margin-bottom:8px">📌 <strong>Preferred assets under this horizon:</strong> ${horizonAssets[node.label] || 'Balanced allocation'}</div>
      <div class="h-rich-note">💡 The chosen horizon acts as a weighting multiplier on the Criteria level — long horizons amplify the Return criterion; short horizons amplify Liquidity. The current model defaults to Long-term, driving higher equity allocations.</div>
    </div>`;
  }

  // ── SCENARIO NODES ──
  else if (node.type === 'scenario') {
    const scenarioImpact = {
      'Bull Market':   { equities: '↑ High', bonds: '↓ Low', real: '↑ High', cash: '↓ Low', color: 'var(--green)' },
      'Stagflation':   { equities: '↓ Low', bonds: '↓ Low', real: '↑ High', cash: '→ Neutral', color: 'var(--red)' },
      'Deflation':     { equities: '↓ Low', bonds: '↑ High', real: '↓ Low', cash: '↑ High', color: 'var(--accent2)' },
      'Steady Growth': { equities: '↑ Moderate', bonds: '→ Neutral', real: '↑ Moderate', cash: '↓ Low', color: 'var(--yellow)' },
    };
    const si = scenarioImpact[node.label] || {};
    html = `<div class="h-rich-panel">
      <div class="h-rich-title" style="color:${si.color||'var(--text)'}">📊 Scenario: ${node.label}</div>
      <div class="h-rich-desc">${node.desc}</div>
      <div class="h-rich-stats">
        <div class="h-rich-stat"><div class="h-rich-stat-val">${si.equities||'—'}</div><div class="h-rich-stat-lbl">Equities</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val">${si.bonds||'—'}</div><div class="h-rich-stat-lbl">Bonds</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val">${si.real||'—'}</div><div class="h-rich-stat-lbl">Real Assets</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val">${si.cash||'—'}</div><div class="h-rich-stat-lbl">Cash/MM</div></div>
      </div>
      <div class="h-rich-note">💡 The active scenario adjusts expected return inputs and pairwise comparison biases. To stress-test a different scenario, change the Macro Scenario dropdown in the Dashboard and re-run the model.</div>
    </div>`;
  }

  // ── CRITERION NODES ──
  else if (node.type === 'criterion') {
    const cw = state.result?.criteria_weights || {};
    const liveWeight = cw[node.label] ? pct(cw[node.label]) : (node.approxWeight ? pct(node.approxWeight) : '~');
    const scCount = node.subCriteria?.length || 0;
    const saatyCriterionMap = { 'Return': 2, 'Risk': 3, 'Liquidity': 5, 'Diversification': 3 };
    html = `<div class="h-rich-panel">
      <div class="h-rich-title">⚖️ Criterion: ${node.label}</div>
      <div class="h-rich-desc">${node.desc}</div>
      <div class="h-rich-stats">
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--accent2)">${liveWeight}</div><div class="h-rich-stat-lbl">Current Weight</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--text)">${scCount}</div><div class="h-rich-stat-lbl">Sub-criteria</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--green)">${node.subCriteria?.map(s=>s.label).join(', ') || 'None'}</div><div class="h-rich-stat-lbl">Components</div></div>
      </div>
      ${scCount > 0 ? `<div class="h-rich-note" style="margin-bottom:10px">📌 Click any sub-criterion node above to drill into its detailed analysis and live asset rankings.</div>` : ''}
      <div class="h-rich-override">
        <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin-bottom:8px">Manual Override — Adjust Relative Importance</div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <label style="font-size:.78rem;color:var(--muted);min-width:120px">${node.label} importance:</label>
          <select id="manual_${node.label}" class="form-control" style="width:220px;font-size:.78rem" onchange="">
            <option value="0.5">0.5 — Half as important as baseline</option>
            <option value="1" selected>1.0 — Baseline (AI calibration)</option>
            <option value="1.5">1.5 — Moderately more important</option>
            <option value="2">2.0 — Twice as important</option>
            <option value="3">3.0 — Three times as important</option>
            <option value="5">5.0 — Strongly more important</option>
          </select>
          <button class="btn" style="padding:5px 14px;font-size:.78rem" onclick="applyManualCriterion('${node.label}')">Apply Override</button>
        </div>
        <div style="font-size:.73rem;color:var(--muted);margin-top:6px">Override scales this criterion's pairwise row entries before re-running the model via the stress-test endpoint. Results appear in the Dashboard automatically.</div>
      </div>
    </div>`;
  }

  // ── ASSET NODES ──
  else if (node.type === 'asset') {
    const w  = state.result?.constrained_weights || {};
    const ev = state.evidence?.evidence || {};
    const liveAlloc = w[node.label] ? pct(w[node.label]) : '— (run model)';
    const d  = ev[node.label] || {};
    html = `<div class="h-rich-panel">
      <div class="h-rich-title">🏦 Asset: ${node.label}</div>
      <div class="h-rich-desc">${node.desc}</div>
      <div class="h-rich-stats">
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--accent2)">${liveAlloc}</div><div class="h-rich-stat-lbl">Current Allocation</div></div>
        ${d.expected_return != null ? `<div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--green)">${d.expected_return.toFixed(1)}%</div><div class="h-rich-stat-lbl">E[R]</div></div>` : ''}
        ${d.beta != null ? `<div class="h-rich-stat"><div class="h-rich-stat-val">${d.beta.toFixed(2)}</div><div class="h-rich-stat-lbl">Beta</div></div>` : ''}
        ${d.volatility != null ? `<div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--yellow)">${d.volatility.toFixed(1)}%</div><div class="h-rich-stat-lbl">Volatility</div></div>` : ''}
        ${d.sharpe != null ? `<div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--text)">${d.sharpe.toFixed(2)}</div><div class="h-rich-stat-lbl">Sharpe</div></div>` : ''}
        ${d.max_drawdown != null ? `<div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--red)">${d.max_drawdown.toFixed(1)}%</div><div class="h-rich-stat-lbl">Max DD</div></div>` : ''}
      </div>
      <div class="h-rich-note">💡 To explore how changing this asset's Saaty scores affects the overall allocation, run a <strong>Practitioner Stress Test</strong> from the AHP Matrices tab.</div>
    </div>`;
  }

  if (html) {
    panel.innerHTML = html;
    panel.classList.add('visible');
  }
}

function selectHSubNode(nodeId, levelIdx, nodeIdx, subIdx) {
  document.querySelectorAll(`#h-level-${levelIdx} .h-node`).forEach(n => n.classList.remove('active'));
  const el = document.getElementById(nodeId);
  if (el) el.classList.add('active');

  const criterion = HIERARCHY_DATA.criteria[nodeIdx];
  const sc = criterion?.subCriteria?.[subIdx];
  if (!sc) return;

  // Find matching SUB_CRIT_DATA entry
  const groupKey = sc.dataKey; // 'return', 'risk', 'liquidity', 'diversification'
  const scItems  = SUB_CRIT_DATA[groupKey] || [];
  // Match by label prefix
  const scItem   = scItems.find(i => sc.label.toLowerCase().includes(i.id.toLowerCase()) ||
                                     i.label.toLowerCase().includes(sc.label.toLowerCase().split(' ')[0]));

  const ev = state.evidence?.evidence || {};
  const assetKeys = Object.keys(ev);

  let liveHtml = '';
  if (scItem?.liveKey && assetKeys.length) {
    const withData = assetKeys.filter(a => ev[a]?.[scItem.liveKey] != null);
    if (withData.length) {
      const sorted = [...withData].sort((a, b) => {
        const va = ev[a][scItem.liveKey], vb = ev[b][scItem.liveKey];
        return scItem.better === 'lower' ? va - vb : vb - va;
      });
      liveHtml = `<div class="h-rich-live">
        <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--green);margin-bottom:6px">Live Rankings — ${sc.label}</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">` +
        sorted.map((a, i) => `<span style="padding:3px 10px;border-radius:12px;font-size:.73rem;background:${i===0?'rgba(16,185,129,.2)':i===sorted.length-1?'rgba(239,68,68,.15)':'var(--surface3)'};border:1px solid ${i===0?'var(--green)':i===sorted.length-1?'var(--red)':'var(--border)'};color:${i===0?'var(--green)':i===sorted.length-1?'var(--red)':'var(--muted)'}">
          ${i+1}. ${a} <strong>${scItem.format(ev[a][scItem.liveKey])}</strong>
        </span>`).join('') +
        `</div></div>`;
    }
  }

  const panel = document.getElementById(`h-detail-${levelIdx}`);
  if (panel) {
    panel.innerHTML = `<div class="h-rich-panel">
      <div class="h-rich-title">📐 ${sc.label} <span style="font-size:.72rem;color:var(--muted);font-weight:400">↳ sub-criterion of ${criterion.label}</span></div>
      ${scItem ? `<div class="h-rich-desc">${scItem.detail}</div>` : `<div class="h-rich-desc">${sc.desc}</div>`}
      ${scItem ? `<div class="h-rich-stats">
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--accent)">${sc.weight || scItem.weight}</div><div class="h-rich-stat-lbl">Model Weight</div></div>
        <div class="h-rich-stat"><div class="h-rich-stat-val" style="color:var(--yellow);font-size:.72rem">${scItem.better==='lower'?'Lower = Better':'Higher = Better'}</div><div class="h-rich-stat-lbl">Direction</div></div>
      </div>` : ''}
      ${liveHtml}
      ${scItem?.pensionNote ? `<div class="h-rich-note">💡 ${scItem.pensionNote}</div>` : ''}
    </div>`;
    panel.classList.add('visible');
  }
}

// ── MANUAL CRITERION OVERRIDE ─────────────────────────────
async function applyManualCriterion(criterionName) {
  const selectEl = document.getElementById(`manual_${criterionName}`);
  if (!selectEl) return;
  const multiplier = parseFloat(selectEl.value);

  // Base AI Saaty pairs for criteria
  const basePairs = {
    'Return vs Risk': 2, 'Return vs Liquidity': 5, 'Return vs Diversification': 3,
    'Risk vs Liquidity': 3, 'Risk vs Diversification': 2, 'Liquidity vs Diversification': 0.5,
  };
  const criteria = {};
  for (const [pair, base] of Object.entries(basePairs)) {
    const [a, b] = pair.split(' vs ');
    let val = base;
    if (a === criterionName) val = Math.min(9, Math.max(1/9, base * multiplier));
    else if (b === criterionName) val = Math.min(9, Math.max(1/9, base / multiplier));
    criteria[pair] = val;
  }

  try {
    const r = await fetch('/api/stress-test', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ criteria }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);

    // Show quick comparison in the detail panel
    const assets = Object.keys(data.base_weights || {});
    const rows = assets.map(a => {
      const base  = ((data.base_weights[a]||0)*100).toFixed(1);
      const cust  = ((data.custom_weights[a]||0)*100).toFixed(1);
      const delta = ((data.deltas[a]||0)*100).toFixed(1);
      const col   = data.deltas[a] > 0.005 ? 'var(--green)' : data.deltas[a] < -0.005 ? 'var(--red)' : 'var(--muted)';
      return `<div style="display:grid;grid-template-columns:130px 52px 52px 55px;gap:6px;font-size:.77rem;padding:4px 0;border-bottom:1px solid var(--border)">
        <span>${a}</span><span style="color:var(--muted)">${base}%</span>
        <span style="color:var(--accent2)">${cust}%</span>
        <span style="color:${col}">${parseFloat(delta)>=0?'+':''}${delta}pp</span>
      </div>`;
    });
    const overrideResult = document.createElement('div');
    overrideResult.style.marginTop = '12px';
    overrideResult.innerHTML = `<div style="font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:6px">Override Result — ${criterionName} ×${multiplier}</div>
      <div style="display:grid;grid-template-columns:130px 52px 52px 55px;gap:6px;font-size:.67rem;color:var(--muted);padding:0 0 6px;text-transform:uppercase;letter-spacing:.04em"><span>Asset</span><span>AI</span><span>Override</span><span>Δ</span></div>
      ${rows.join('')}`;

    const panel = document.querySelector('.h-detail-panel.visible');
    if (panel) {
      const existing = panel.querySelector('.override-result');
      if (existing) existing.remove();
      overrideResult.className = 'override-result';
      panel.appendChild(overrideResult);
    }
    toast(`${criterionName} override applied (×${multiplier})`);
  } catch(e) {
    toast('Override failed: ' + e.message, 'error');
  }
}

// ── DECISION BREAKDOWN ────────────────────────────────────
function updateDecisionBreakdown(result, evidence) {
  if (!result) return;
  const w  = result.constrained_weights || {};
  const cw = result.criteria_weights || {};
  const assets = Object.keys(w);

  // Step 1: Evidence gathered
  const step1 = document.getElementById('bd-step1');
  if (step1 && evidence && evidence.evidence) {
    const topByReturn = [...assets]
      .filter(a => evidence.evidence[a])
      .sort((a,b) => (evidence.evidence[b]?.expected_return||0) - (evidence.evidence[a]?.expected_return||0))
      .slice(0, 3);
    step1.innerHTML = '<table style="width:100%;font-size:.78rem"><tbody>' +
      topByReturn.map(a => {
        const d = evidence.evidence[a];
        return `<tr>
          <td style="padding:4px 0;font-weight:600">${a}</td>
          <td style="color:var(--green)">E[R]=${d.expected_return.toFixed(1)}%</td>
          <td style="color:var(--muted)">β=${d.beta.toFixed(2)}, Vol=${d.volatility.toFixed(1)}%</td>
          <td style="color:var(--muted);font-size:.72rem">drove high Return score</td>
        </tr>`;
      }).join('') + '</tbody></table>';
  } else if (step1) {
    const topByWeight = [...assets].sort((a,b) => (w[b]||0)-(w[a]||0)).slice(0,3);
    step1.innerHTML = '<div style="color:var(--muted);font-size:.78rem">Top weighted assets: ' +
      topByWeight.map(a => a + ' (' + pct(w[a]) + ')').join(' · ') + '</div>';
  }

  // Step 2: Pairwise judgments
  const step2 = document.getElementById('bd-step2');
  if (step2) {
    const sorted = [...assets].sort((a,b) => (w[b]||0)-(w[a]||0));
    const pairs = [];
    for (let i = 0; i < Math.min(3, sorted.length - 1); i++) {
      const a1 = sorted[i], a2 = sorted[i+1];
      const ratio = w[a1] > 0 && w[a2] > 0 ? (w[a1]/w[a2]).toFixed(2) : '—';
      pairs.push(`<div style="padding:5px 0;border-bottom:1px solid var(--border);font-size:.78rem">
        <span style="font-weight:600">${a1}</span> vs <span style="font-weight:600">${a2}</span> on Return:
        <span style="color:var(--accent2)"> ${ratio}</span>
        <span style="color:var(--muted)"> (ratio from synthesis)</span>
      </div>`);
    }
    step2.innerHTML = pairs.join('') || '<div style="color:var(--muted)">No data</div>';
  }

  // Step 3: Criteria weighting bar
  const step3 = document.getElementById('bd-step3');
  if (step3 && Object.keys(cw).length) {
    const maxCW = Math.max(...Object.values(cw));
    step3.innerHTML = Object.entries(cw).map(([c, v]) =>
      `<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">
        <div style="width:110px;font-size:.77rem;font-weight:500">${c}</div>
        <div style="flex:1;background:var(--surface3);border-radius:4px;height:10px;overflow:hidden">
          <div style="width:${(v/maxCW*100).toFixed(1)}%;height:100%;background:var(--accent);border-radius:4px"></div>
        </div>
        <div style="width:42px;text-align:right;font-size:.77rem;font-weight:700;color:var(--accent2)">${pct(v)}</div>
      </div>`
    ).join('');
  }

  // Step 4: Final synthesis
  const step4 = document.getElementById('bd-step4');
  if (step4) {
    const summary = [...assets].sort((a,b) => (w[b]||0)-(w[a]||0))
      .map(a => `${a.split(' ')[0]} ${pct(w[a])}`).join(', ');
    step4.innerHTML = `
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:6px">AHP weighted sum synthesis →</div>
      <div style="font-size:.8rem;line-height:1.8">${summary}</div>`;
  }
}

function toggleBreakdown(header) {
  const body = header.nextElementSibling;
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  header.classList.toggle('open', !isOpen);
}

// ── PREFERENCE ELICITATION ────────────────────────────────
function switchPrefTab(mode, btn) {
  document.querySelectorAll('.pref-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.pref-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('pref-' + mode).classList.add('active');
  if (mode === 'allocate') buildAllocateSliders();
}

function buildAllocateSliders() {
  const wrap = document.getElementById('allocateSliders');
  if (!wrap || wrap.children.length > 0) return;
  const assetList = ['Small Stocks','Large Stocks','Corp Bonds','Govt Bonds','Real Estate','Money Market','Commodities'];
  const defaultVal = Math.round(100 / assetList.length);
  wrap.innerHTML = assetList.map(a => {
    const id = 'allocSlider_' + a.replace(/ /g,'_');
    return `<div>
      <div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:4px">
        <span>${a}</span><span id="${id}_val" style="color:var(--accent2)">${defaultVal}%</span>
      </div>
      <input type="range" id="${id}" min="0" max="60" value="${defaultVal}"
             style="width:100%;accent-color:var(--accent)"
             oninput="document.getElementById('${id}_val').textContent=this.value+'%';updateAllocateTotal()">
    </div>`;
  }).join('');
}

function updateAllocateTotal() {
  const assetKeys = ['Small_Stocks','Large_Stocks','Corp_Bonds','Govt_Bonds','Real_Estate','Money_Market','Commodities'];
  const total = assetKeys.reduce((sum, k) => sum + parseInt(document.getElementById('allocSlider_'+k)?.value||0), 0);
  const el = document.getElementById('allocateTotal');
  if (el) {
    el.textContent = total + '%';
    el.style.color = total === 100 ? 'var(--green)' : total > 100 ? 'var(--red)' : 'var(--yellow)';
  }
}

function checkPrefOverride(select, aiValue) {
  const pairKey = select.id.replace('prefSaaty_', '');
  const badgeId = 'badge_' + pairKey;
  const badge = document.getElementById(badgeId);
  if (!badge) return;
  const isOverride = Math.abs(parseFloat(select.value) - parseFloat(aiValue)) > 0.001;
  badge.classList.toggle('show', isOverride);
}

async function applyUserPreferences() {
  const saatyActive    = document.getElementById('pref-saaty')?.classList.contains('active');
  const verbalActive   = document.getElementById('pref-verbal')?.classList.contains('active');
  const allocateActive = document.getElementById('pref-allocate')?.classList.contains('active');

  if (allocateActive) {
    const assetList = [
      ['Small Stocks','Small_Stocks'],['Large Stocks','Large_Stocks'],['Corp Bonds','Corp_Bonds'],
      ['Govt Bonds','Govt_Bonds'],['Real Estate','Real_Estate'],['Money Market','Money_Market'],['Commodities','Commodities']
    ];
    const total = assetList.reduce((s,[,k]) => s + parseInt(document.getElementById('allocSlider_'+k)?.value||0), 0);
    if (total !== 100) { toast('Weights must sum to 100% before applying', 'error'); return; }
    showManualAllocationComparison(assetList);
    return;
  }

  const criteria = {};
  if (saatyActive) {
    criteria['Return vs Risk']               = parseFloat(document.getElementById('prefSaaty_Return_Risk')?.value || 2);
    criteria['Return vs Liquidity']          = parseFloat(document.getElementById('prefSaaty_Return_Liquidity')?.value || 5);
    criteria['Return vs Diversification']    = parseFloat(document.getElementById('prefSaaty_Return_Diversification')?.value || 3);
    criteria['Risk vs Liquidity']            = parseFloat(document.getElementById('prefSaaty_Risk_Liquidity')?.value || 3);
    criteria['Risk vs Diversification']      = parseFloat(document.getElementById('prefSaaty_Risk_Diversification')?.value || 2);
    criteria['Liquidity vs Diversification'] = parseFloat(document.getElementById('prefSaaty_Liquidity_Diversification')?.value || 0.5);
  } else if (verbalActive) {
    const rv  = parseInt(document.getElementById('prefSlider_Return')?.value || 5);
    const rsk = parseInt(document.getElementById('prefSlider_Risk')?.value || 5);
    const liq = parseInt(document.getElementById('prefSlider_Liquidity')?.value || 5);
    const div = parseInt(document.getElementById('prefSlider_Diversification')?.value || 5);
    criteria['Return vs Risk']               = rv  / rsk;
    criteria['Return vs Liquidity']          = rv  / liq;
    criteria['Return vs Diversification']    = rv  / div;
    criteria['Risk vs Liquidity']            = rsk / liq;
    criteria['Risk vs Diversification']      = rsk / div;
    criteria['Liquidity vs Diversification'] = liq / div;
  }

  try {
    const r = await fetch('/api/stress-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criteria }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    showPrefComparison(data);
    toast('Preferences applied — see comparison below');
  } catch(e) {
    toast('Could not apply preferences: ' + e.message, 'error');
  }
}

function showPrefComparison(data) {
  const result  = document.getElementById('prefCompareResult');
  const content = document.getElementById('prefCompareContent');
  if (!result || !content) return;
  const assets = Object.keys(data.base_weights || {});
  const rows = assets.map(a => {
    const base  = ((data.base_weights[a]||0)*100).toFixed(1);
    const user  = ((data.custom_weights[a]||0)*100).toFixed(1);
    const delta = ((data.deltas[a]||0)*100).toFixed(1);
    const color = data.deltas[a] > 0.005 ? 'var(--green)' : data.deltas[a] < -0.005 ? 'var(--red)' : 'var(--muted)';
    return `<div style="display:grid;grid-template-columns:140px 55px 55px 60px;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:.78rem">
      <span style="font-weight:500">${a}</span>
      <span style="color:var(--muted)">${base}%</span>
      <span style="color:var(--accent2)">${user}%</span>
      <span style="color:${color}">${parseFloat(delta)>=0?'+':''}${delta}pp</span>
    </div>`;
  });
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:140px 55px 55px 60px;gap:8px;padding:4px 0 8px;font-size:.67rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)">
      <span>Asset</span><span>AI</span><span>You</span><span>Delta</span>
    </div>${rows.join('')}`;
  result.style.display = 'block';
}

function showManualAllocationComparison(assetList) {
  const result  = document.getElementById('prefCompareResult');
  const content = document.getElementById('prefCompareContent');
  if (!result || !content) return;
  const aiWeights = state.result?.constrained_weights || {};
  const rows = assetList.map(([label, key]) => {
    const userVal = parseInt(document.getElementById('allocSlider_'+key)?.value||0);
    const aiVal   = ((aiWeights[label]||0)*100).toFixed(1);
    const delta   = (userVal - parseFloat(aiVal)).toFixed(1);
    const color   = parseFloat(delta) > 0 ? 'var(--green)' : parseFloat(delta) < 0 ? 'var(--red)' : 'var(--muted)';
    return `<div style="display:grid;grid-template-columns:140px 55px 55px 60px;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:.78rem">
      <span style="font-weight:500">${label}</span>
      <span style="color:var(--muted)">${aiVal}%</span>
      <span style="color:var(--accent2)">${userVal}%</span>
      <span style="color:${color}">${parseFloat(delta)>=0?'+':''}${delta}pp</span>
    </div>`;
  });
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:140px 55px 55px 60px;gap:8px;padding:4px 0 8px;font-size:.67rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)">
      <span>Asset</span><span>AI</span><span>You</span><span>Delta</span>
    </div>${rows.join('')}`;
  result.style.display = 'block';
}

// ── CHAT ACTION BUTTONS ───────────────────────────────────
function sendChallengeBtn() {
  if (!state.result) { toast('Run the model first to generate an allocation to challenge', 'error'); return; }
  const top = Object.entries(state.result.constrained_weights || {}).sort((a,b) => b[1]-a[1])[0];
  const msg = top
    ? `I've chosen ${top[0]} at ${pct(top[1])}. Challenge this decision — what is the strongest empirical argument against it?`
    : 'Challenge my top allocation decision — what is the strongest empirical argument against it?';
  document.getElementById('chatInput').value = msg;
  sendChat();
}

function sendCompetitorBtn() {
  const scenario = document.getElementById('cfgScenario')?.value || 'Steady Growth';
  const msg = `Based on the current macro scenario (${scenario}), predict how CalPERS, NYSCRF, and CPPIB are likely to shift their allocations in 2025-2026 and compare to my current position.`;
  document.getElementById('chatInput').value = msg;
  sendChat();
}

// ── HELPERS ───────────────────────────────────────────────────
function pct(v) { return (v * 100).toFixed(1) + '%'; }
function sign(v) { return (v >= 0 ? '+' : '') + v.toFixed(2); }
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function gradeColor(g) {
  return { A:'#10b981', B:'#3b82f6', C:'#f59e0b', F:'#ef4444' }[g] || '#e2e8f0';
}
