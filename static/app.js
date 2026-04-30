'use strict';

/* ===== DOM refs ===== */
const fromInput   = document.getElementById('fromCity');
const toInput     = document.getElementById('toCity');
const dateInput   = document.getElementById('travelDate');
const sleeperOnly = document.getElementById('sleeperOnly');
const directOnly  = document.getElementById('directOnly');
const swapBtn     = document.getElementById('swapBtn');
const searchForm  = document.getElementById('searchForm');
const searchBtn   = document.getElementById('searchBtn');
const btnText     = searchBtn.querySelector('.btn-text');
const btnLoading  = searchBtn.querySelector('.btn-loading');
const warningsEl  = document.getElementById('warnings');
const errorBox    = document.getElementById('errorBox');
const resultsEl   = document.getElementById('results');
const planList    = document.getElementById('planList');
const resultsCount= document.getElementById('resultsCount');
const emptyState  = document.getElementById('emptyState');
const destCard    = document.getElementById('destinationCard');
const destTitle   = document.getElementById('destTitle');
const destLoading = document.getElementById('destLoading');
const destBody    = document.getElementById('destBody');
const destError   = document.getElementById('destError');
const destTabs    = document.getElementById('destTabs');

/* ===== 自动补全 ===== */
let acTimers = {};

function setupAutocomplete(input, listEl) {
  input.addEventListener('input', () => {
    const q = input.value.trim();
    clearTimeout(acTimers[input.id]);
    if (q.length < 1) { hideAC(listEl); return; }
    acTimers[input.id] = setTimeout(() => fetchAC(q, input, listEl), 250);
  });
  input.addEventListener('blur', () => setTimeout(() => hideAC(listEl), 180));
  input.addEventListener('keydown', (e) => handleACKey(e, listEl, input));
}

async function fetchAC(q, input, listEl) {
  try {
    const res = await fetch(`/api/stations/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    renderAC(data, listEl, input);
  } catch { hideAC(listEl); }
}

function renderAC(items, listEl, input) {
  if (!items.length) { hideAC(listEl); return; }
  listEl.innerHTML = items.map((s, i) =>
    `<li data-name="${s.name}" data-idx="${i}">${s.name} <span style="color:#8b90b0;font-size:.8rem">${s.code}</span></li>`
  ).join('');
  listEl.classList.remove('hidden');
  listEl.querySelectorAll('li').forEach(li => {
    li.addEventListener('mousedown', () => {
      input.value = li.dataset.name;
      hideAC(listEl);
    });
  });
}

function hideAC(listEl) { listEl.innerHTML = ''; listEl.classList.add('hidden'); }

function handleACKey(e, listEl, input) {
  const items = listEl.querySelectorAll('li');
  if (!items.length) return;
  const active = listEl.querySelector('.active');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    const next = active ? active.nextElementSibling : items[0];
    if (next) { active?.classList.remove('active'); next.classList.add('active'); }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    const prev = active ? active.previousElementSibling : items[items.length - 1];
    if (prev) { active?.classList.remove('active'); prev.classList.add('active'); }
  } else if (e.key === 'Enter' && active) {
    e.preventDefault();
    input.value = active.dataset.name;
    hideAC(listEl);
  }
}

setupAutocomplete(fromInput, document.getElementById('fromAC'));
setupAutocomplete(toInput,   document.getElementById('toAC'));

/* ===== 交换起终点 ===== */
swapBtn.addEventListener('click', () => {
  [fromInput.value, toInput.value] = [toInput.value, fromInput.value];
});

/* ===== 表单提交 ===== */
searchForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  await doSearch();
});

function setLoading(on) {
  searchBtn.disabled = on;
  btnText.classList.toggle('hidden', on);
  btnLoading.classList.toggle('hidden', !on);
}

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.classList.remove('hidden');
}

function clearMessages() {
  errorBox.classList.add('hidden');
  warningsEl.classList.add('hidden');
  resultsEl.classList.add('hidden');
  emptyState.classList.add('hidden');
  destCard.classList.add('hidden');
  destError.classList.add('hidden');
  destLoading.classList.add('hidden');
  errorBox.textContent = '';
  warningsEl.textContent = '';
  planList.innerHTML = '';
  destBody.innerHTML = '';
  destError.textContent = '';
}

async function doSearch() {
  clearMessages();
  setLoading(true);

  const toCity = toInput.value.trim();
  // 攻略与行程并发请求，互不阻塞
  const destPromise = toCity ? fetchDestination(toCity) : Promise.resolve();

  try {
    const body = {
      from: fromInput.value.trim(),
      to:   toCity,
      date: dateInput.value,
      sleeper_only: sleeperOnly.checked,
      direct_only:  directOnly.checked,
    };
    const res = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || `请求失败（${res.status}）`);
      return;
    }
    if (data.warnings?.length) {
      warningsEl.textContent = '⚠️ ' + data.warnings.join('；');
      warningsEl.classList.remove('hidden');
    }
    if (!data.plans?.length) {
      emptyState.classList.remove('hidden');
      return;
    }
    renderResults(data.plans);
  } catch (err) {
    showError(`网络请求失败：${err.message}`);
  } finally {
    setLoading(false);
  }
  await destPromise;
}

/* ===== 目的地攻略 ===== */
let currentDestTab = 'summary';
let currentDestData = null;

async function fetchDestination(city) {
  destCard.classList.remove('hidden');
  destTitle.textContent = `${city} · 目的地攻略`;
  destLoading.classList.remove('hidden');
  destError.classList.add('hidden');
  destBody.innerHTML = '';
  currentDestData = null;
  currentDestTab = 'summary';
  syncDestTabsActive();

  try {
    const res = await fetch(`/api/destination?city=${encodeURIComponent(city)}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `攻略加载失败（${res.status}）`);
    }
    currentDestData = data;
    if (data.city) destTitle.textContent = `${data.city} · 目的地攻略`;
    renderDestTab(currentDestTab);
  } catch (err) {
    destError.textContent = `📭 暂时无法生成 ${city} 的攻略：${err.message}`;
    destError.classList.remove('hidden');
  } finally {
    destLoading.classList.add('hidden');
  }
}

function syncDestTabsActive() {
  destTabs.querySelectorAll('.dest-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === currentDestTab);
  });
}

function renderDestTab(tab) {
  if (!currentDestData) { destBody.innerHTML = ''; return; }
  if (tab === 'summary') {
    const text = currentDestData.summary || '暂无简介';
    destBody.innerHTML = `<div class="dest-summary">${escapeHTML(text)}</div>`;
    return;
  }
  const list = currentDestData[tab] || [];
  if (!list.length) {
    destBody.innerHTML = `<div class="dest-empty">暂无相关推荐</div>`;
    return;
  }
  const icon = tab === 'foods' ? '🍜' : '🏛️';
  destBody.innerHTML = `
    <ul class="dest-list">
      ${list.map(item => `
        <li class="dest-item">
          <span class="dest-item-icon">${icon}</span>
          <div class="dest-item-text">
            <div class="dest-item-name">${escapeHTML(item.name || '')}</div>
            ${item.desc ? `<div class="dest-item-desc">${escapeHTML(item.desc)}</div>` : ''}
          </div>
        </li>
      `).join('')}
    </ul>`;
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
  }[c]));
}

destTabs.addEventListener('click', (e) => {
  const btn = e.target.closest('.dest-tab');
  if (!btn) return;
  currentDestTab = btn.dataset.tab;
  syncDestTabsActive();
  renderDestTab(currentDestTab);
});

/* ===== 结果渲染 ===== */
function fmtMinutes(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h${m}m` : `${h}h`;
}

function nightPct(ratio) { return Math.round(ratio * 100); }

const REASON_ICONS = ['🌙','☀️','⏱️','🚉','🛏️'];

function buildSegLine(segs) {
  if (segs.length === 1) {
    const s = segs[0];
    return `
      <div class="plan-route">
        <div class="plan-time-block">
          <div class="plan-time">${s.depart_time}</div>
          <div class="plan-date">${s.depart_date.slice(5)}</div>
          <div class="plan-station">${s.from_station}</div>
        </div>
        <div class="plan-middle">
          <div class="plan-line">
            <div class="line-dot"></div>
            <div class="line-bar"></div>
            <div class="line-dot"></div>
          </div>
          <div class="plan-train-no">${s.train_no} · ${s.train_type}</div>
          <div class="plan-duration">${fmtMinutes(s.duration_minutes)}</div>
        </div>
        <div class="plan-time-block">
          <div class="plan-time">${s.arrive_time}</div>
          <div class="plan-date">${s.arrive_date.slice(5)}</div>
          <div class="plan-station">${s.to_station}</div>
        </div>
      </div>`;
  }
  // 中转：A ──[车次1]── B(换乘) ──[车次2]── C 单行三段式
  const s1 = segs[0], s2 = segs[1];
  const waitMin = computeWaitMinutes(s1, s2);
  return `
    <div class="plan-route plan-route-transfer">
      <div class="plan-station-block">
        <div class="plan-time">${s1.depart_time}</div>
        <div class="plan-date">${s1.depart_date.slice(5)}</div>
        <div class="plan-station">${s1.from_station}</div>
      </div>

      <div class="plan-leg">
        <div class="plan-train-no">${s1.train_no} · ${s1.train_type}</div>
        <div class="plan-line">
          <div class="line-dot"></div>
          <div class="line-bar"></div>
          <div class="line-arrow">▶</div>
        </div>
        <div class="plan-duration">${fmtMinutes(s1.duration_minutes)}</div>
      </div>

      <div class="plan-station-block plan-station-transfer">
        <div class="plan-transfer-badge">换乘</div>
        <div class="plan-time-pair">
          <span class="plan-time-small">${s1.arrive_time}</span>
          <span class="plan-time-sep">→</span>
          <span class="plan-time-small">${s2.depart_time}</span>
        </div>
        <div class="plan-station">${s1.to_station}</div>
        <div class="plan-wait">候车 ${fmtMinutes(waitMin)}</div>
      </div>

      <div class="plan-leg">
        <div class="plan-train-no">${s2.train_no} · ${s2.train_type}</div>
        <div class="plan-line">
          <div class="line-dot"></div>
          <div class="line-bar"></div>
          <div class="line-arrow">▶</div>
        </div>
        <div class="plan-duration">${fmtMinutes(s2.duration_minutes)}</div>
      </div>

      <div class="plan-station-block">
        <div class="plan-time">${s2.arrive_time}</div>
        <div class="plan-date">${s2.arrive_date.slice(5)}</div>
        <div class="plan-station">${s2.to_station}</div>
      </div>
    </div>`;
}

function computeWaitMinutes(s1, s2) {
  // 通过出发到达日期+时间精确计算候车分钟数，跨日安全
  const arr = new Date(`${s1.arrive_date}T${s1.arrive_time}:00`);
  const dep = new Date(`${s2.depart_date}T${s2.depart_time}:00`);
  const diff = Math.round((dep - arr) / 60000);
  return diff > 0 ? diff : 0;
}

function buildTags(plan) {
  const tags = [];
  const pct = nightPct(plan.night_ratio);
  if (pct > 0) tags.push(`<span class="tag tag-night">🌙 夜间占比 ${pct}%</span>`);
  if (plan.arrives_morning) tags.push(`<span class="tag tag-morning">☀️ 早晨到达</span>`);
  if (plan.has_sleeper)     tags.push(`<span class="tag tag-sleeper">🛏️ 有卧铺</span>`);
  if (plan.is_direct)       tags.push(`<span class="tag tag-direct">直达</span>`);
  tags.push(`<span class="tag tag-score">综合评分 ${(plan.score * 100).toFixed(0)}</span>`);
  return tags.join('');
}

function buildReasons(reasons) {
  return reasons.map((r, i) =>
    `<div class="reason-item"><span class="reason-icon">${REASON_ICONS[i] || '·'}</span>${r}</div>`
  ).join('');
}

function renderResults(plans) {
  resultsCount.textContent = plans.length;
  planList.innerHTML = plans.map((plan, idx) => {
    const topPick = idx < 3 && plan.night_ratio >= 0.5 ? 'top-pick' : '';
    return `
      <div class="plan-card ${topPick}">
        ${buildSegLine(plan.segments)}
        <div class="plan-tags">${buildTags(plan)}</div>
        <div class="plan-reasons">${buildReasons(plan.reasons)}</div>
      </div>`;
  }).join('');
  resultsEl.classList.remove('hidden');
  resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
