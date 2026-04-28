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
  errorBox.textContent = '';
  warningsEl.textContent = '';
  planList.innerHTML = '';
}

async function doSearch() {
  clearMessages();
  setLoading(true);
  try {
    const body = {
      from: fromInput.value.trim(),
      to:   toInput.value.trim(),
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
}

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
  // 中转：两段
  const s1 = segs[0], s2 = segs[1];
  return `
    <div class="plan-route">
      <div class="plan-time-block">
        <div class="plan-time">${s1.depart_time}</div>
        <div class="plan-date">${s1.depart_date.slice(5)}</div>
        <div class="plan-station">${s1.from_station}</div>
      </div>
      <div class="plan-middle">
        <div class="plan-line">
          <div class="line-dot"></div>
          <div class="line-bar"></div>
          <div class="line-dot"></div>
        </div>
        <div class="plan-train-no">${s1.train_no} · ${s1.train_type}</div>
        <div class="plan-duration">${fmtMinutes(s1.duration_minutes)}</div>
        <div class="transfer-node">🔄 ${s1.to_station} 换乘 ${s2.depart_time} 发</div>
        <div class="plan-line">
          <div class="line-dot"></div>
          <div class="line-bar"></div>
          <div class="line-dot"></div>
        </div>
        <div class="plan-train-no">${s2.train_no} · ${s2.train_type}</div>
        <div class="plan-duration">${fmtMinutes(s2.duration_minutes)}</div>
      </div>
      <div class="plan-time-block">
        <div class="plan-time">${s2.arrive_time}</div>
        <div class="plan-date">${s2.arrive_date.slice(5)}</div>
        <div class="plan-station">${s2.to_station}</div>
      </div>
    </div>`;
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
