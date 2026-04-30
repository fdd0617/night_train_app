/**
 * 夜行列车推荐 — 前端主脚本
 *
 * 整体用 IIFE 包裹，避免污染全局作用域；内部按职责拆模块（DOM / Theme / Storage /
 * Hash / API / Autocomplete / Search / Render / Favorites）。
 */
(() => {
  'use strict';

  // ─────────────────────────────────────────────
  // DOM 引用
  // ─────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  const dom = {
    fromInput:    $('fromCity'),
    toInput:      $('toCity'),
    dateInput:    $('travelDate'),
    sleeperOnly:  $('sleeperOnly'),
    directOnly:   $('directOnly'),
    multiDay:     $('multiDay'),       // 可选：多日查询开关（F2）
    swapBtn:      $('swapBtn'),
    searchForm:   $('searchForm'),
    searchBtn:    $('searchBtn'),
    btnText:      null,
    btnLoading:   null,
    warningsEl:   $('warnings'),
    errorBox:     $('errorBox'),
    resultsEl:    $('results'),
    planList:     $('planList'),
    resultsCount: $('resultsCount'),
    emptyState:   $('emptyState'),
    destCard:     $('destinationCard'),
    destTitle:    $('destTitle'),
    destLoading:  $('destLoading'),
    destBody:     $('destBody'),
    destError:    $('destError'),
    destTabs:     $('destTabs'),
    fromAC:       $('fromAC'),
    toAC:         $('toAC'),
    themeToggle:  $('themeToggle'),
    favList:      $('favList'),
    favSection:   $('favSection'),
    favEmpty:     $('favEmpty'),
    multiDayCard: $('multiDayCard'),
    multiDayList: $('multiDayList'),
  };
  if (dom.searchBtn) {
    dom.btnText = dom.searchBtn.querySelector('.btn-text');
    dom.btnLoading = dom.searchBtn.querySelector('.btn-loading');
  }

  const escapeHTML = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));

  const fmtMinutes = (min) => {
    const h = Math.floor(min / 60);
    const m = min % 60;
    return m ? `${h}h${m}m` : `${h}h`;
  };
  const nightPct = (ratio) => Math.round(ratio * 100);

  // ─────────────────────────────────────────────
  // 主题（Light / Dark）
  // ─────────────────────────────────────────────
  const Theme = {
    KEY: 'ntr.theme',
    apply(t) {
      document.documentElement.dataset.theme = t;
      if (dom.themeToggle) {
        dom.themeToggle.textContent = t === 'light' ? '🌙' : '☀️';
        dom.themeToggle.title = t === 'light' ? '切换到深色模式' : '切换到浅色模式';
      }
    },
    init() {
      let saved = null;
      try { saved = localStorage.getItem(this.KEY); } catch {}
      const sys = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
      this.apply(saved || sys);
      dom.themeToggle?.addEventListener('click', () => this.toggle());
    },
    toggle() {
      const cur = document.documentElement.dataset.theme || 'dark';
      const next = cur === 'dark' ? 'light' : 'dark';
      this.apply(next);
      try { localStorage.setItem(this.KEY, next); } catch {}
    },
  };

  // ─────────────────────────────────────────────
  // 本地存储（最近查询 + 收藏）
  // ─────────────────────────────────────────────
  const Storage = {
    LAST_QUERY: 'ntr.lastQuery',
    FAVORITES:  'ntr.favorites',

    _safeRead(key) {
      try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; }
    },
    _safeWrite(key, val) {
      try { localStorage.setItem(key, JSON.stringify(val)); } catch {}
    },

    saveQuery(q) { this._safeWrite(this.LAST_QUERY, q); },
    loadQuery()  { return this._safeRead(this.LAST_QUERY); },

    listFavorites() { return this._safeRead(this.FAVORITES) || []; },
    addFavorite(f) {
      const list = this.listFavorites();
      const id = `${f.from}__${f.to}`;
      if (list.find((x) => x.id === id)) return false;
      list.unshift({ id, from: f.from, to: f.to, ts: Date.now() });
      this._safeWrite(this.FAVORITES, list.slice(0, 20));
      return true;
    },
    removeFavorite(id) {
      const list = this.listFavorites().filter((x) => x.id !== id);
      this._safeWrite(this.FAVORITES, list);
    },
    isFavorited(from, to) {
      return !!this.listFavorites().find((x) => x.id === `${from}__${to}`);
    },
  };

  // ─────────────────────────────────────────────
  // URL Hash 编解码（用于分享链接 / 浏览器历史恢复）
  // 形如：#from=北京&to=上海&date=2026-05-01&sleeper=1&direct=0
  // ─────────────────────────────────────────────
  const Hash = {
    write(q) {
      const params = new URLSearchParams();
      if (q.from)         params.set('from', q.from);
      if (q.to)           params.set('to', q.to);
      if (q.date)         params.set('date', q.date);
      if (q.sleeper_only) params.set('sleeper', '1');
      if (q.direct_only)  params.set('direct', '1');
      if (q.multi_day)    params.set('multi', '1');
      const hash = params.toString();
      const next = hash ? `#${hash}` : '';
      if (location.hash !== next) {
        history.replaceState(null, '', location.pathname + location.search + next);
      }
    },
    read() {
      if (!location.hash || location.hash.length < 2) return null;
      const params = new URLSearchParams(location.hash.slice(1));
      const from = params.get('from');
      const to = params.get('to');
      if (!from || !to) return null;
      return {
        from, to,
        date: params.get('date') || '',
        sleeper_only: params.get('sleeper') === '1',
        direct_only:  params.get('direct')  === '1',
        multi_day:    params.get('multi')   === '1',
      };
    },
  };

  // ─────────────────────────────────────────────
  // API
  // ─────────────────────────────────────────────
  const API = {
    async stations(q) {
      const res = await fetch(`/api/stations/search?q=${encodeURIComponent(q)}`);
      return res.json();
    },
    async recommend(body) {
      const res = await fetch('/api/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      return { ok: res.ok, status: res.status, data };
    },
    async destination(city) {
      const res = await fetch(`/api/destination?city=${encodeURIComponent(city)}`);
      const data = await res.json();
      return { ok: res.ok, status: res.status, data };
    },
  };

  // ─────────────────────────────────────────────
  // 自动补全
  // ─────────────────────────────────────────────
  const Autocomplete = (() => {
    const timers = {};

    function setup(input, listEl) {
      input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(timers[input.id]);
        if (q.length < 1) { hide(listEl); return; }
        timers[input.id] = setTimeout(() => fetchAndRender(q, input, listEl), 250);
      });
      input.addEventListener('blur', () => setTimeout(() => hide(listEl), 180));
      input.addEventListener('keydown', (e) => handleKey(e, listEl, input));
    }

    async function fetchAndRender(q, input, listEl) {
      try {
        const data = await API.stations(q);
        if (!Array.isArray(data) || !data.length) return hide(listEl);
        listEl.innerHTML = data.map((s) =>
          `<li data-name="${escapeHTML(s.name)}">${escapeHTML(s.name)} <span class="ac-code">${escapeHTML(s.code)}</span></li>`
        ).join('');
        listEl.classList.remove('hidden');
        listEl.querySelectorAll('li').forEach((li) => {
          li.addEventListener('mousedown', () => {
            input.value = li.dataset.name;
            hide(listEl);
          });
        });
      } catch {
        hide(listEl);
      }
    }

    function hide(listEl) {
      listEl.innerHTML = '';
      listEl.classList.add('hidden');
    }

    function handleKey(e, listEl, input) {
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
        hide(listEl);
      }
    }

    return { setup };
  })();

  // ─────────────────────────────────────────────
  // 渲染
  // ─────────────────────────────────────────────
  const REASON_ICONS = ['🌙', '☀️', '⏱️', '🚉', '🛏️'];

  function computeWaitMinutes(s1, s2) {
    const arr = new Date(`${s1.arrive_date}T${s1.arrive_time}:00`);
    const dep = new Date(`${s2.depart_date}T${s2.depart_time}:00`);
    const diff = Math.round((dep - arr) / 60000);
    return diff > 0 ? diff : 0;
  }

  function buildSegLine(segs) {
    if (segs.length === 1) {
      const s = segs[0];
      return `
        <div class="plan-route">
          <div class="plan-time-block">
            <div class="plan-time">${escapeHTML(s.depart_time)}</div>
            <div class="plan-date">${escapeHTML(s.depart_date.slice(5))}</div>
            <div class="plan-station">${escapeHTML(s.from_station)}</div>
          </div>
          <div class="plan-middle">
            <div class="plan-line">
              <div class="line-dot"></div>
              <div class="line-bar"></div>
              <div class="line-dot"></div>
            </div>
            <div class="plan-train-no">${escapeHTML(s.train_no)} · ${escapeHTML(s.train_type)}</div>
            <div class="plan-duration">${fmtMinutes(s.duration_minutes)}</div>
          </div>
          <div class="plan-time-block">
            <div class="plan-time">${escapeHTML(s.arrive_time)}</div>
            <div class="plan-date">${escapeHTML(s.arrive_date.slice(5))}</div>
            <div class="plan-station">${escapeHTML(s.to_station)}</div>
          </div>
        </div>`;
    }
    const s1 = segs[0], s2 = segs[1];
    const waitMin = computeWaitMinutes(s1, s2);
    return `
      <div class="plan-route plan-route-transfer">
        <div class="plan-station-block">
          <div class="plan-time">${escapeHTML(s1.depart_time)}</div>
          <div class="plan-date">${escapeHTML(s1.depart_date.slice(5))}</div>
          <div class="plan-station">${escapeHTML(s1.from_station)}</div>
        </div>
        <div class="plan-leg">
          <div class="plan-train-no">${escapeHTML(s1.train_no)} · ${escapeHTML(s1.train_type)}</div>
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
            <span class="plan-time-small">${escapeHTML(s1.arrive_time)}</span>
            <span class="plan-time-sep">→</span>
            <span class="plan-time-small">${escapeHTML(s2.depart_time)}</span>
          </div>
          <div class="plan-station">${escapeHTML(s1.to_station)}</div>
          <div class="plan-wait">候车 ${fmtMinutes(waitMin)}</div>
        </div>
        <div class="plan-leg">
          <div class="plan-train-no">${escapeHTML(s2.train_no)} · ${escapeHTML(s2.train_type)}</div>
          <div class="plan-line">
            <div class="line-dot"></div>
            <div class="line-bar"></div>
            <div class="line-arrow">▶</div>
          </div>
          <div class="plan-duration">${fmtMinutes(s2.duration_minutes)}</div>
        </div>
        <div class="plan-station-block">
          <div class="plan-time">${escapeHTML(s2.arrive_time)}</div>
          <div class="plan-date">${escapeHTML(s2.arrive_date.slice(5))}</div>
          <div class="plan-station">${escapeHTML(s2.to_station)}</div>
        </div>
      </div>`;
  }

  function buildTags(plan) {
    const tags = [];
    const pct = nightPct(plan.night_ratio);
    if (pct > 0)              tags.push(`<span class="tag tag-night">🌙 夜间占比 ${pct}%</span>`);
    if (plan.arrives_morning) tags.push(`<span class="tag tag-morning">☀️ 早晨到达</span>`);
    if (plan.has_sleeper)     tags.push(`<span class="tag tag-sleeper">🛏️ 有卧铺</span>`);
    if (plan.is_direct)       tags.push(`<span class="tag tag-direct">直达</span>`);
    tags.push(`<span class="tag tag-score">综合评分 ${(plan.score * 100).toFixed(0)}</span>`);
    return tags.join('');
  }

  function buildReasons(reasons) {
    return reasons.map((r, i) =>
      `<div class="reason-item"><span class="reason-icon">${REASON_ICONS[i] || '·'}</span>${escapeHTML(r)}</div>`
    ).join('');
  }

  function renderResults(plans) {
    dom.resultsCount.textContent = plans.length;
    dom.planList.innerHTML = plans.map((plan, idx) => {
      const topPick = idx < 3 && plan.night_ratio >= 0.5 ? 'top-pick' : '';
      return `
        <div class="plan-card ${topPick}">
          ${buildSegLine(plan.segments)}
          <div class="plan-tags">${buildTags(plan)}</div>
          <div class="plan-reasons">${buildReasons(plan.reasons)}</div>
        </div>`;
    }).join('');
    dom.resultsEl.classList.remove('hidden');
    dom.resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ─────────────────────────────────────────────
  // 目的地攻略
  // ─────────────────────────────────────────────
  const Destination = (() => {
    let currentTab = 'summary';
    let currentData = null;

    async function load(city) {
      dom.destCard.classList.remove('hidden');
      dom.destTitle.textContent = `${city} · 目的地攻略`;
      dom.destLoading.classList.remove('hidden');
      dom.destError.classList.add('hidden');
      dom.destBody.innerHTML = '';
      currentData = null;
      currentTab = 'summary';
      syncTabs();

      try {
        const { ok, status, data } = await API.destination(city);
        if (!ok) throw new Error(data.error || `攻略加载失败（${status}）`);
        currentData = data;
        if (data.city) dom.destTitle.textContent = `${data.city} · 目的地攻略`;
        renderTab(currentTab);
      } catch (err) {
        dom.destError.textContent = `📭 暂时无法生成 ${city} 的攻略：${err.message}`;
        dom.destError.classList.remove('hidden');
      } finally {
        dom.destLoading.classList.add('hidden');
      }
    }

    function syncTabs() {
      dom.destTabs.querySelectorAll('.dest-tab').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.tab === currentTab);
      });
    }

    function renderTab(tab) {
      if (!currentData) { dom.destBody.innerHTML = ''; return; }
      if (tab === 'summary') {
        const text = currentData.summary || '暂无简介';
        dom.destBody.innerHTML = `<div class="dest-summary">${escapeHTML(text)}</div>`;
        return;
      }
      const list = currentData[tab] || [];
      if (!list.length) {
        dom.destBody.innerHTML = `<div class="dest-empty">暂无相关推荐</div>`;
        return;
      }
      const icon = tab === 'foods' ? '🍜' : '🏛️';
      dom.destBody.innerHTML = `
        <ul class="dest-list">
          ${list.map((item) => `
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

    dom.destTabs?.addEventListener('click', (e) => {
      const btn = e.target.closest('.dest-tab');
      if (!btn) return;
      currentTab = btn.dataset.tab;
      syncTabs();
      renderTab(currentTab);
    });

    return { load };
  })();

  // ─────────────────────────────────────────────
  // 收藏
  // ─────────────────────────────────────────────
  const Favorites = {
    refresh() {
      const list = Storage.listFavorites();
      if (!dom.favList) return;
      if (!list.length) {
        dom.favList.innerHTML = '';
        dom.favEmpty?.classList.remove('hidden');
        return;
      }
      dom.favEmpty?.classList.add('hidden');
      dom.favList.innerHTML = list.map((f) => `
        <li class="fav-item" data-id="${escapeHTML(f.id)}">
          <button type="button" class="fav-apply" data-from="${escapeHTML(f.from)}" data-to="${escapeHTML(f.to)}">
            ⭐ ${escapeHTML(f.from)} → ${escapeHTML(f.to)}
          </button>
          <button type="button" class="fav-remove" title="移除收藏" data-id="${escapeHTML(f.id)}">×</button>
        </li>
      `).join('');
    },
    bind() {
      if (!dom.favList) return;
      dom.favList.addEventListener('click', (e) => {
        const apply = e.target.closest('.fav-apply');
        const remove = e.target.closest('.fav-remove');
        if (apply) {
          dom.fromInput.value = apply.dataset.from;
          dom.toInput.value = apply.dataset.to;
          Search.run();
        } else if (remove) {
          Storage.removeFavorite(remove.dataset.id);
          Favorites.refresh();
        }
      });
    },
  };

  // ─────────────────────────────────────────────
  // 表单 / 搜索
  // ─────────────────────────────────────────────
  const Search = (() => {
    function setLoading(on) {
      dom.searchBtn.disabled = on;
      dom.btnText?.classList.toggle('hidden', on);
      dom.btnLoading?.classList.toggle('hidden', !on);
    }

    function showError(msg) {
      dom.errorBox.textContent = msg;
      dom.errorBox.classList.remove('hidden');
    }

    function clearMessages() {
      dom.errorBox.classList.add('hidden');
      dom.warningsEl.classList.add('hidden');
      dom.resultsEl.classList.add('hidden');
      dom.emptyState.classList.add('hidden');
      dom.destCard.classList.add('hidden');
      dom.destError.classList.add('hidden');
      dom.destLoading.classList.add('hidden');
      if (dom.multiDayCard) dom.multiDayCard.classList.add('hidden');
      dom.errorBox.textContent = '';
      dom.warningsEl.textContent = '';
      dom.planList.innerHTML = '';
      dom.destBody.innerHTML = '';
      dom.destError.textContent = '';
    }

    function readQuery() {
      return {
        from: dom.fromInput.value.trim(),
        to:   dom.toInput.value.trim(),
        date: dom.dateInput.value,
        sleeper_only: dom.sleeperOnly.checked,
        direct_only:  dom.directOnly.checked,
        multi_day:    !!dom.multiDay?.checked,
      };
    }

    function applyQuery(q) {
      if (!q) return;
      dom.fromInput.value = q.from || '';
      dom.toInput.value = q.to || '';
      if (q.date) dom.dateInput.value = q.date;
      if (typeof q.sleeper_only === 'boolean') dom.sleeperOnly.checked = q.sleeper_only;
      if (typeof q.direct_only === 'boolean')  dom.directOnly.checked  = q.direct_only;
      if (dom.multiDay && typeof q.multi_day === 'boolean') {
        dom.multiDay.checked = q.multi_day;
      }
    }

    async function run() {
      const q = readQuery();
      if (!q.from || !q.to) { showError('出发地与目的地不能为空'); return; }

      Storage.saveQuery(q);
      Hash.write(q);

      clearMessages();
      setLoading(true);

      const destPromise = q.to ? Destination.load(q.to) : Promise.resolve();

      try {
        if (q.multi_day) {
          await runMultiDay(q);
          return;
        }
        const { ok, status, data } = await API.recommend(q);
        if (!ok) {
          showError(data.error || `请求失败（${status}）`);
          return;
        }
        if (data.warnings?.length) {
          dom.warningsEl.textContent = '⚠️ ' + data.warnings.join('；');
          dom.warningsEl.classList.remove('hidden');
        }
        if (!data.plans?.length) {
          dom.emptyState.classList.remove('hidden');
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

    async function runMultiDay(q) {
      // 多日查询走专用接口，前端展示每日最佳并允许下钻
      try {
        const res = await fetch('/api/recommend/multi-day', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(q),
        });
        const data = await res.json();
        if (!res.ok) {
          showError(data.error || `多日查询失败（${res.status}）`);
          return;
        }
        renderMultiDay(data);
      } catch (err) {
        showError(`多日查询失败：${err.message}`);
      }
    }

    function renderMultiDay(payload) {
      const days = payload.days || [];
      if (!days.length) { dom.emptyState.classList.remove('hidden'); return; }
      const best = payload.best;

      const items = days.map((d) => {
        const isBest = best && d.date === best.date;
        if (!d.plan) {
          return `<li class="md-item md-empty"><div class="md-date">${escapeHTML(d.date)}</div><div class="md-msg">该日无夜行方案</div></li>`;
        }
        const p = d.plan;
        return `
          <li class="md-item ${isBest ? 'md-best' : ''}" data-date="${escapeHTML(d.date)}">
            <div class="md-head">
              <span class="md-date">${escapeHTML(d.date)} ${isBest ? '<span class="md-best-tag">最佳</span>' : ''}</span>
              <span class="md-score">评分 ${(p.score * 100).toFixed(0)}</span>
            </div>
            <div class="md-route">${escapeHTML(p.depart_time)} → ${escapeHTML(p.arrive_time)} · ${fmtMinutes(p.total_minutes)}${p.is_direct ? ' · 直达' : ' · 中转'}${p.has_sleeper ? ' · 卧铺' : ''}</div>
            <button type="button" class="md-detail" data-date="${escapeHTML(d.date)}">查看当日全部方案 →</button>
          </li>`;
      }).join('');

      dom.multiDayList.innerHTML = items;
      dom.multiDayCard.classList.remove('hidden');
      dom.multiDayCard.scrollIntoView({ behavior: 'smooth', block: 'start' });

      // 下钻：点击某天 → 用该日期单日查询
      dom.multiDayList.querySelectorAll('.md-detail').forEach((btn) => {
        btn.addEventListener('click', () => {
          dom.dateInput.value = btn.dataset.date;
          if (dom.multiDay) dom.multiDay.checked = false;
          run();
        });
      });
    }

    return { run, applyQuery };
  })();

  // ─────────────────────────────────────────────
  // 启动
  // ─────────────────────────────────────────────
  function init() {
    Theme.init();
    Autocomplete.setup(dom.fromInput, dom.fromAC);
    Autocomplete.setup(dom.toInput,   dom.toAC);

    dom.swapBtn?.addEventListener('click', () => {
      [dom.fromInput.value, dom.toInput.value] = [dom.toInput.value, dom.fromInput.value];
    });

    dom.searchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      Search.run();
    });

    Favorites.refresh();
    Favorites.bind();

    // 优先级：URL hash > localStorage 最近查询
    const restored = Hash.read() || Storage.loadQuery();
    if (restored) {
      Search.applyQuery(restored);
      // 只有 URL hash 才自动触发查询（分享链接场景）；localStorage 仅回填表单
      if (Hash.read()) Search.run();
    }

    // 浏览器前进/后退时重新加载查询
    window.addEventListener('hashchange', () => {
      const q = Hash.read();
      if (q) {
        Search.applyQuery(q);
        Search.run();
      }
    });
  }

  // 暴露最小 API 给"收藏当前查询"按钮（在 index.html 中绑定）
  window.NTR = {
    favoriteCurrent() {
      const from = dom.fromInput.value.trim();
      const to = dom.toInput.value.trim();
      if (!from || !to) return false;
      const ok = Storage.addFavorite({ from, to });
      Favorites.refresh();
      return ok;
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
