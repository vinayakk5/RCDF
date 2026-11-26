// ============================================================
// FIRM -> RM WORKSPACE
// Pick a firm, pick an RM (main tender), see everything of that RM in one place.
// Loaded after index.html's main script; reuses its state, pages, nav and api helpers.
// ============================================================
(function () {
  const ws = window.ws = {};
  // First visit on a device: start with all firms rather than whichever firm is first.
  try { if (!localStorage.getItem('rcdf-context-v1')) state.globalView = true; } catch {}
  const _origLoadCtx = loadContextFromStorage;
  loadContextFromStorage = function () {
    let had = false;
    try { had = Boolean(localStorage.getItem('rcdf-context-v1')); } catch {}
    _origLoadCtx();
    if (!had) state.globalView = true;
  };

  // ── formatting ─────────────────────────────────────────────
  ws.money = function (v) {
    const n = Number(v) || 0;
    if (!n) return '—';
    const a = Math.abs(n);
    if (a >= 1e7) return '₹' + (n / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 }) + ' Cr';
    if (a >= 1e5) return '₹' + (n / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 2 }) + ' L';
    return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 });
  };
  ws.full = v => (v === null || v === undefined || v === '') ? '—' : '₹' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  ws.qtl = v => (Number(v) || 0) ? Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }) + ' qtl' : '—';
  ws.num = v => (Number(v) || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  ws.date = function (s) {
    if (!s) return '—';
    const d = new Date(String(s).slice(0, 10) + 'T00:00:00');
    if (isNaN(d)) return escapeHtml(s);
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  };
  const esc = s => escapeHtml(s === null || s === undefined ? '' : String(s));
  const firmShort = name => String(name || '').replace(/^shree\s+/i, '').replace(/\s+(industries|trading company|enterprises)$/i, '');
  const firmName = id => (state.companies || []).find(c => String(c.id) === String(id))?.name || '';

  // GET with explicit query (no automatic context), always fresh.
  ws.get = function (path, params) {
    const qs = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '') qs.set(k, v); });
    const q = qs.toString();
    return apiFetchRaw(path + (q ? (path.includes('?') ? '&' : '?') + q : ''));
  };

  // ── scope: a firm is enough to work; an RM narrows further ─
  hasScopedContext = function () { return Boolean(state.globalView || state.context.companyId); };
  const ALWAYS_OPEN = new Set(['home', 'rms', 'rm', 'pending-ingests', 'busy-staging', 'whatsapp', 'auto-approval',
    'users', 'brokers', 'audit', 'market']);
  canAccessWorkspace = function (page) {
    return ALWAYS_OPEN.has(page) || Boolean(state.globalView || state.context.companyId);
  };

  ws.setFirm = async function (id) {
    if (!id) {
      state.globalView = true;
      state.context.mainTenderId = null;
    } else {
      state.globalView = false;
      if (String(state.context.companyId) !== String(id)) state.context.mainTenderId = null;
      state.context.companyId = parseInt(id, 10);
      try { state.mainTenders = await apiFetchRaw(`/main-tenders?company_id=${state.context.companyId}`); } catch { state.mainTenders = []; }
    }
    saveContextToStorage();
    renderContextBar();
    if (state.currentPage === 'rm') return nav('rms');
    try { state.deals = await apiFetch('/deals'); } catch {}
    pages[state.currentPage]?.load();
  };

  ws.useRm = async function (rm) {
    // Make an RM the working context so every older screen is filtered to it.
    state.globalView = false;
    state.context.companyId = rm.company_id;
    state.context.mainTenderId = rm.id;
    try { state.mainTenders = await apiFetchRaw(`/main-tenders?company_id=${rm.company_id}`); } catch {}
    if (!state.mainTenders.some(t => String(t.id) === String(rm.id))) {
      state.mainTenders.push({ id: rm.id, company_id: rm.company_id, tender_code: rm.tender_code, title: rm.title });
    }
    saveContextToStorage();
    renderContextBar();
  };

  ws.clearRm = function () {
    state.context.mainTenderId = null;
    saveContextToStorage();
    renderContextBar();
    if (state.currentPage === 'rm') return nav('rms');
    pages[state.currentPage]?.load();
  };

  // ── the bar under the title: firm tabs, RM chip, search ────
  renderContextBar = function () {
    const el = document.getElementById('context-bar');
    if (!el) return;
    const all = state.globalView;
    const firms = (state.companies || []).map(c => `<button class="${!all && String(c.id) === String(state.context.companyId) ? 'on' : ''}"
        title="${esc(c.name)}" onclick="ws.setFirm(${c.id})">${esc(firmShort(c.name))}</button>`).join('');
    const mt = !all ? selectedMainTender() : null;
    const rmChip = mt
      ? `<span class="wsb-rm"><button class="wsb-rm-name" onclick="ws.openRm(${mt.id})">${esc(mt.tender_code)}</button><button class="wsb-x" title="Show all RMs" onclick="ws.clearRm()">✕</button></span>`
      : `<button class="wsb-rm wsb-rm-all" onclick="nav('rms')">All RMs ▾</button>`;
    el.innerHTML = `<div class="wsb">
      <div class="wsb-firms" role="tablist"><button class="${all ? 'on' : ''}" onclick="ws.setFirm(null)">All firms</button>${firms}</div>
      ${rmChip}
      <button class="wsb-search" onclick="ws.openSearch()">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>
        <span>Search RM, PO, truck, bill…</span><kbd>Ctrl K</kbd>
      </button>
    </div>`;
  };

  // ── nav: remember where we are in the URL so Back works ────
  const origNav = nav;
  nav = function (page, el) {
    origNav(page, el);
    const titles = { rms: 'Tenders (RM)', rm: 'RM' };
    if (titles[page] && page !== 'rm') document.getElementById('page-title').textContent = titles[page];
    if (page !== 'rm') ws.setHash(page === 'rms' ? '#/rms' : `#/${page}`);
  };
  ws.setHash = function (h) {
    if (location.hash !== h) history.pushState(null, '', h);
  };
  ws.startFromHash = function () {
    const m = location.hash.match(/^#\/rm\/(\d+)(?:\/([a-z-]+))?/);
    if (m) { ws.openRm(parseInt(m[1], 10), m[2] || 'overview', true); return true; }
    const p = location.hash.match(/^#\/([a-z-]+)$/);
    if (p && pages[p[1]] && p[1] !== 'rm') { nav(p[1]); return true; }
    return false;
  };
  window.addEventListener('popstate', () => { if (!ws.startFromHash()) nav('rms'); });

  // ── debounce searches typed into the older screens ─────────
  const _timers = {};
  const origRerender = rerenderWithInputFocus;
  rerenderWithInputFocus = function (inputId, renderFn) {
    if (!inputId) return origRerender(inputId, renderFn);
    clearTimeout(_timers[inputId]);
    return new Promise(res => { _timers[inputId] = setTimeout(() => res(origRerender(inputId, renderFn)), 250); });
  };

  // ============================================================
  // RM LIST
  // ============================================================
  pages.rms = {
    status: 'active', q: '', from: '', to: '', rows: [], counts: {}, loading: false,

    async load() {
      const el = document.getElementById('page-rms');
      setTopbarActions(`<button class="btn" onclick="ws.newRm()">+ New RM</button>`, 'rms');
      if (!this.rows.length) el.innerHTML = '<div class="loading">Loading tenders</div>';
      try {
        const res = await ws.get('/workspace/rms', {
          company_id: state.globalView ? null : state.context.companyId,
          status: 'all', date_from: this.from, date_to: this.to,
        });
        this.rows = res.rows || [];
        this.counts = res.counts || {};
        this.inboxOnly = res.inbox_only || [];
      } catch (e) {
        el.innerHTML = `<div class="loading">Could not load tenders. ${esc(e.message)}</div>`;
        return;
      }
      this.render();
    },

    filtered() {
      const toks = this.q.toLowerCase().split(/\s+/).filter(Boolean);
      return this.rows.filter(r => {
        if (this.status !== 'all' && r.status !== this.status) return false;
        if (!toks.length) return true;
        const hay = [r.tender_code, r.title, r.company, ...(r.plants || []), ...(r.materials || [])].join(' ').toLowerCase();
        return toks.every(t => hay.includes(t));
      });
    },

    render() {
      const el = document.getElementById('page-rms');
      const rows = this.filtered();
      const c = this.counts || {};
      const seg = ['active', 'closed', 'archived', 'all'].map(s => `<button class="${this.status === s ? 'on' : ''}" onclick="pages.rms.setStatus('${s}')">${s[0].toUpperCase() + s.slice(1)} <span class="ws-count">${c[s] ?? 0}</span></button>`).join('');
      const showFirm = state.globalView;
      const scopeLabel = state.globalView ? 'All firms' : esc(firmName(state.context.companyId) || 'Select a firm');
      const totalPending = rows.reduce((a, r) => a + (r.pending_docs || 0) + (r.bills_to_check || 0), 0);

      el.innerHTML = `<div class="ws-page">
        <div class="ws-head">
          <div>
            <div class="ws-eyebrow">${scopeLabel}</div>
            <h1 class="ws-h1">Tenders</h1>
          </div>
          <div class="ws-head-note">${rows.length} RM${rows.length === 1 ? '' : 's'}${totalPending ? ` · <b>${totalPending}</b> waiting to check` : ''}</div>
        </div>
        <div class="ws-filters">
          <div class="ws-search-inline">
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>
            <input id="rms-q" placeholder="Filter by RM, plant or material" value="${esc(this.q)}" oninput="pages.rms.setQ(this.value)">
          </div>
          <div class="seg ws-seg">${seg}</div>
          <label class="ws-date">From <input type="date" value="${esc(this.from)}" onchange="pages.rms.setDate('from', this.value)"></label>
          <label class="ws-date">To <input type="date" value="${esc(this.to)}" onchange="pages.rms.setDate('to', this.value)"></label>
          ${(this.from || this.to) ? `<button class="btn btn-sm" onclick="pages.rms.clearDates()">Clear dates</button>` : ''}
        </div>
        ${rows.length ? this.table(rows, showFirm) + this.cards(rows, showFirm) : this.empty()}
        ${this.inboxOnlyHtml()}
      </div>`;
    },

    inboxOnlyHtml() {
      const list = (this.inboxOnly || []).filter(r => !this.q || r.tender_code.toLowerCase().includes(this.q.toLowerCase()));
      if (!list.length || this.status === 'closed' || this.status === 'archived') return '';
      const label = { purchase_order: 'PO', tender_notice: 'notice', plant_unloading: 'unloading', rejection_notice: 'rejection', purchase_bill: 'bill', not_classified: 'other' };
      return `<div class="ws-section-h" style="margin-top:22px">Seen in email, not set up yet
          <span class="ws-sub">documents mention these RMs, but no PO for them has been approved</span></div>
        <div class="ws-chips">${list.map(r => `<button class="ws-chip" onclick="ws.openSearch('${esc(r.tender_code)}')">
          <span class="ws-code">${esc(r.tender_code)}</span>
          <span class="ws-sub">${Object.entries(r.pending_docs_by_type).map(([k, n]) => `${n} ${label[k] || k}`).join(' · ')}</span></button>`).join('')}</div>`;
    },

    progress(r) {
      const pct = Math.max(0, Math.min(100, r.progress_pct || 0));
      return `<div class="ws-prog" title="Accepted ${ws.num(r.accepted_qtl)} of ${ws.num(r.tender_qty_qtl)} qtl"><div style="width:${pct}%"></div></div>
        <div class="ws-sub">${pct ? pct + '% accepted' : 'Nothing unloaded yet'}</div>`;
    },

    supply(r) {
      if (!r.supply_end) return '<span class="ws-sub">No dates</span>';
      let tag = '';
      if (r.status === 'active') {
        if (r.supply_over) tag = '<span class="pill pill-pending">Supply period over</span>';
        else if (r.days_left !== null && r.days_left <= 3) tag = `<span class="pill pill-danger">${r.days_left} day${r.days_left === 1 ? '' : 's'} left</span>`;
        else if (r.days_left !== null) tag = `<span class="ws-sub">${r.days_left} days left</span>`;
      }
      return `<div>${ws.date(r.supply_start)} – ${ws.date(r.supply_end)}</div>${tag}`;
    },

    todo(r) {
      const n = (r.pending_docs || 0) + (r.bills_to_check || 0);
      return n ? `<span class="ws-badge">${n} to check</span>` : '<span class="ws-sub">—</span>';
    },

    statusPill(s) {
      return s === 'active' ? '<span class="pill pill-active">Active</span>'
        : s === 'closed' ? '<span class="pill pill-muted">Closed</span>' : '<span class="pill pill-muted">Archived</span>';
    },

    table(rows, showFirm) {
      return `<div class="tbl-wrap ws-table"><table class="tbl"><thead><tr>
          <th>RM</th>${showFirm ? '<th>Firm</th>' : ''}<th>Plants · material</th><th>Supply</th>
          <th class="r">Ordered</th><th style="min-width:130px">Progress</th><th class="r">PO value</th><th>To check</th><th>Status</th>
        </tr></thead><tbody>
        ${rows.map(r => `<tr class="ws-row" onclick="ws.openRm(${r.id})">
          <td><div class="ws-code">${esc(r.tender_code)}</div><div class="ws-sub">${r.po_count} PO${r.po_count === 1 ? '' : 's'} · ${r.subtenders} sub-tender${r.subtenders === 1 ? '' : 's'}</div></td>
          ${showFirm ? `<td>${esc(firmShort(r.company))}</td>` : ''}
          <td><div>${esc((r.plants || []).join(', ') || '—')}</div><div class="ws-sub">${esc((r.materials || []).join(', '))}</div></td>
          <td>${this.supply(r)}</td>
          <td class="num r">${ws.qtl(r.tender_qty_qtl)}</td>
          <td>${this.progress(r)}</td>
          <td class="num r">${ws.money(r.po_amount)}</td>
          <td>${this.todo(r)}</td>
          <td>${this.statusPill(r.status)}</td>
        </tr>`).join('')}
        </tbody></table></div>`;
    },

    cards(rows, showFirm) {
      return `<div class="ws-cards">${rows.map(r => `<button class="ws-card" onclick="ws.openRm(${r.id})">
          <div class="ws-card-top"><span class="ws-code">${esc(r.tender_code)}</span>${this.statusPill(r.status)}${(r.pending_docs || 0) + (r.bills_to_check || 0) ? this.todo(r) : ''}</div>
          ${showFirm ? `<div class="ws-sub">${esc(r.company)}</div>` : ''}
          <div>${esc((r.plants || []).join(', ') || 'No plant yet')} <span class="ws-sub">· ${esc((r.materials || []).join(', '))}</span></div>
          <div class="ws-card-grid">
            <div><div class="ws-k">Ordered</div><div class="num">${ws.qtl(r.tender_qty_qtl)}</div></div>
            <div><div class="ws-k">PO value</div><div class="num">${ws.money(r.po_amount)}</div></div>
            <div><div class="ws-k">Supply</div><div>${r.supply_end ? ws.date(r.supply_end) : '—'}</div></div>
          </div>
          ${this.progress(r)}
        </button>`).join('')}</div>`;
    },

    empty() {
      if (this.rows.length) return `<div class="ws-empty">No RM matches these filters.</div>`;
      return `<div class="ws-empty">
        <div class="ws-empty-h">No tenders for this firm yet</div>
        <div>An RM appears here once one of its purchase orders is approved in the Inbox. POs arrive by email automatically.</div>
        <button class="btn btn-primary" style="margin-top:12px" onclick="nav('pending-ingests')">Open Inbox</button>
      </div>`;
    },

    setStatus(s) { this.status = s; this.render(); },
    setQ(v) { this.q = v; rerenderWithInputFocus('rms-q', () => this.render()); },
    setDate(k, v) { this[k] = v; this.load(); },
    clearDates() { this.from = ''; this.to = ''; this.load(); },
  };

  ws.newRm = async function () {
    if (state.globalView || !state.context.companyId) return toast('Pick a firm first', 'warn');
    await createMainTenderPrompt();
    pages.rms.load();
  };

  // ============================================================
  // ONE RM
  // ============================================================
  const TABS = [
    ['overview', 'Overview'], ['pos', 'Purchase orders'], ['inbox', 'To check'], ['bills', 'Bills'],
    ['dispatch', 'Dispatch'], ['unloading', 'Unloading'], ['rejections', 'Rejections'],
    ['sales', 'Sales bills'], ['payments', 'Payments'],
  ];

  ws.openRm = async function (id, tab, fromHash) {
    pages.rm.id = id;
    pages.rm.tab = tab || (String(pages.rm.lastId) === String(id) ? pages.rm.tab : 'overview') || 'overview';
    pages.rm.lastId = id;
    nav('rm');
    if (!fromHash) ws.setHash(`#/rm/${id}/${pages.rm.tab}`);
    else history.replaceState(null, '', `#/rm/${id}/${pages.rm.tab}`);
  };

  pages.rm = {
    id: null, tab: 'overview', data: null, docs: null,

    async load() {
      const el = document.getElementById('page-rm');
      if (!this.id) return nav('rms');
      el.innerHTML = '<div class="loading">Loading RM</div>';
      try {
        this.data = await ws.get(`/workspace/rms/${this.id}`);
      } catch (e) {
        el.innerHTML = `<div class="ws-page"><div class="ws-empty">Could not open this RM. ${esc(e.message)}</div></div>`;
        return;
      }
      await ws.useRm(this.data);
      this.docs = null;
      document.getElementById('page-title').textContent = this.data.tender_code;
      setTopbarActions(this.actions(), `rm:${this.id}:${this.data.status}`, true);
      this.render();
    },

    actions() {
      const s = this.data.status;
      const b = [];
      if (s === 'active') b.push(`<button class="btn" onclick="pages.rm.setStatus('closed')">Close RM</button>`);
      if (s !== 'archived') b.push(`<button class="btn" onclick="pages.rm.setStatus('archived')">Archive</button>`);
      if (s !== 'active') b.push(`<button class="btn btn-primary" onclick="pages.rm.setStatus('active')">Reopen</button>`);
      return `<div style="display:flex;gap:8px">${b.join('')}</div>`;
    },

    async setStatus(s) {
      const done = { closed: 'closed', archived: 'archived', active: 'reopened' };
      try {
        await apiFetchRaw(`/main-tenders/${this.id}`, { method: 'PATCH', body: JSON.stringify({ status: s }) });
        toast(`${this.data.tender_code} ${done[s]}. Nothing was deleted.`, 'ok');
        pages.rms.rows = [];
        this.load();
      } catch {}
    },

    kpis() {
      const d = this.data;
      const k = (label, value, sub, cls = '') => `<div class="ws-kpi ${cls}"><div class="ws-k">${label}</div><div class="ws-kv">${value}</div>${sub ? `<div class="ws-sub">${sub}</div>` : ''}</div>`;
      const toCheck = (d.pending_docs || 0) + (d.bills_to_check || 0);
      return `<div class="ws-kpis">
        ${k('Ordered', ws.qtl(d.tender_qty_qtl), `${d.subtenders || 0} sub-tender${d.subtenders === 1 ? '' : 's'}`)}
        ${k('PO value', ws.money(d.po_amount), `${d.po_count || 0} PO${d.po_count === 1 ? '' : 's'}`)}
        ${k('Dispatched', ws.qtl(d.dispatched_qtl), `${d.dispatches || 0} trucks`)}
        ${k('Accepted', ws.qtl(d.accepted_qtl), `${d.progress_pct || 0}% of order`)}
        ${k('Rejected', ws.qtl(d.rejected_qtl), '', d.rejected_qtl ? 'warn' : '')}
        ${k('To pay', ws.money(d.to_pay), `${d.purchase_bills || 0} purchase bills`)}
        ${k('Sales billed', ws.money(d.sales_amount), `${d.sales_bills || 0} sales bills`)}
        ${k('To check', toCheck || '0', 'documents and bills', toCheck ? 'attn' : '')}
      </div>`;
    },

    render() {
      const d = this.data;
      const el = document.getElementById('page-rm');
      const counts = {
        pos: d.po_count, inbox: (d.pending_docs || 0), bills: d.bills, dispatch: d.dispatches,
        unloading: d.unloading_rows, sales: d.sales_bills, payments: d.purchase_bills,
      };
      const tabs = TABS.map(([k, label]) => `<button class="${this.tab === k ? 'on' : ''}" onclick="pages.rm.setTab('${k}')">${label}${counts[k] ? ` <span class="ws-count">${counts[k]}</span>` : ''}</button>`).join('');
      const others = (d.same_rm_other_firms || []).map(o => `<button class="btn btn-xs" onclick="ws.openRm(${o.id})">${esc(firmShort(o.company))}</button>`).join(' ');
      el.innerHTML = `<div class="ws-page">
        <div class="ws-crumbs"><a onclick="nav('rms')">Tenders</a> <span>›</span> ${esc(firmShort(d.company))} <span>›</span> <b>${esc(d.tender_code)}</b></div>
        <div class="ws-head">
          <div>
            <div class="ws-eyebrow">${esc(d.company || '')}</div>
            <h1 class="ws-h1">${esc(d.tender_code)} ${pages.rms.statusPill(d.status)}</h1>
            <div class="ws-head-sub">${esc((d.plants || []).join(', ') || 'No plant yet')} · ${esc((d.materials || []).join(', ') || '—')}
              · Supply ${ws.date(d.supply_start)} – ${ws.date(d.supply_end)}
              ${d.status === 'active' && d.supply_over ? ' <span class="pill pill-pending">Supply period over</span>' : ''}</div>
            ${others ? `<div class="ws-head-sub">Same RM also under: ${others}</div>` : ''}
          </div>
        </div>
        ${this.kpis()}
        <div class="ws-tabs" role="tablist">${tabs}</div>
        <div id="rm-tab-body" class="ws-tab-body"><div class="loading">Loading</div></div>
      </div>`;
      this.renderTab();
    },

    setTab(t) {
      this.tab = t;
      history.replaceState(null, '', `#/rm/${this.id}/${t}`);
      document.querySelectorAll('#page-rm .ws-tabs button').forEach(b => b.classList.toggle('on', (b.getAttribute('onclick') || '').includes(`'${t}'`)));
      this.renderTab();
    },

    async renderTab() {
      const body = document.getElementById('rm-tab-body');
      if (!body) return;
      const tab = this.tab;
      body.innerHTML = '<div class="loading">Loading</div>';
      let html = '';
      try {
        html = await (this['tab_' + tab] || this.tab_overview).call(this);
      } catch (e) {
        html = `<div class="ws-empty">Could not load this list. ${esc(e.message || '')}</div>`;
      }
      if (this.tab === tab) body.innerHTML = html;
    },

    fullPage(page, label) {
      return `<div class="ws-tab-foot"><button class="btn btn-sm" onclick="nav('${page}')">${label || 'Open full screen to edit'} →</button></div>`;
    },

    emptyRow(msg) { return `<div class="ws-empty">${msg}</div>`; },

    // ── tabs ──
    async tab_overview() {
      const d = this.data;
      const sub = d.subtender_rows || [];
      const deals = d.deals || [];
      return `
        <div class="ws-section-h">Sub-tenders <span class="ws-sub">one per plant and material, made from the POs</span></div>
        ${sub.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Sub-tender</th><th>Plant</th><th>Material</th>
          <th class="r">Ordered</th><th class="r">Our rate</th><th>Supply till</th><th>PO</th><th class="r">Dispatched</th><th class="r">Accepted</th><th class="r">Rejected</th><th class="r">Balance</th></tr></thead><tbody>
          ${sub.map(t => `<tr><td>${esc(t.tender_number)}</td><td>${esc(t.plant)}</td><td>${esc(t.material)}</td>
            <td class="num r">${ws.qtl(t.qty_qtl)}</td><td class="num r">${t.sale_rate_per_qtl ? ws.full(t.sale_rate_per_qtl) : '—'}</td>
            <td>${ws.date(t.supply_end)}</td><td>${esc(t.po_number || '—')}</td>
            <td class="num r">${ws.qtl(t.dispatched_qtl)}</td><td class="num r">${ws.qtl(t.accepted_qtl)}</td>
            <td class="num r">${ws.qtl(t.rejected_qtl)}</td><td class="num r">${ws.qtl(t.balance_qtl)}</td></tr>`).join('')}
          </tbody></table></div>` : this.emptyRow('No sub-tenders yet. They are made when a PO for this RM is approved.')}
        <div class="ws-section-h" style="margin-top:18px">Deals with brokers</div>
        ${deals.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Deal</th><th>Broker</th><th>Material</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Dispatched</th><th class="r">Accepted</th><th>Status</th></tr></thead><tbody>
          ${deals.map(x => `<tr><td>${esc(x.deal_number)}</td><td>${esc(x.broker)}</td><td>${esc(x.material)}</td><td class="num r">${ws.qtl(x.deal_qty_qtl)}</td>
            <td class="num r">${ws.full(x.rate_per_qtl)}</td><td class="num r">${ws.qtl(x.dispatched_qtl)}</td><td class="num r">${ws.qtl(x.accepted_qtl)}</td><td>${statusPill(x.status)}</td></tr>`).join('')}
          </tbody></table></div>` : this.emptyRow('No broker deals for this RM yet.')}
        ${this.fullPage('deals', 'Add or edit deals')}`;
    },

    async tab_pos() {
      const pos = this.data.purchase_orders || [];
      if (!pos.length) return this.emptyRow('No purchase order approved for this RM yet. Check the “To check” tab for POs waiting in the Inbox.');
      return `<div class="ws-po-list">${pos.map(p => {
        const lines = p.lines || [];
        const printedDiffers = p.document_total && Math.abs(p.document_total - p.our_amount) > 1;
        return `<div class="ws-po">
          <div class="ws-po-head">
            <div><div class="ws-code">PO ${esc(p.po_number)}</div><div class="ws-sub">${ws.date(p.po_date)} · ${esc(p.plant_name || '—')} · ${esc(p.buyer_name || '')}</div></div>
            <div class="ws-po-actions">
              ${p.doc_url ? `<a class="btn btn-sm" href="${esc(p.doc_url)}" target="_blank" rel="noopener">Open PO document</a>` : '<span class="ws-sub">PO file not on this computer</span>'}
              <button class="btn btn-sm" onclick="pages.rm.poPreview(${p.id})">Sub-tender preview</button>
            </div>
          </div>
          <table class="tbl"><thead><tr><th>Material</th><th class="r">Qty</th><th class="r">Rate / qtl</th><th class="r">Amount</th></tr></thead><tbody>
          ${lines.map(it => {
            const q = Number(it.approved_quantity_qtl || it.quantity_qtl || 0), r = Number(it.approved_rate_per_qtl || it.rate_per_qtl || 0);
            return `<tr><td>${esc(it.material_type || it.material || '—')}</td><td class="num r">${ws.qtl(q)}</td><td class="num r">${ws.full(r)}</td><td class="num r">${ws.full(q * r || it.line_amount)}</td></tr>`;
          }).join('')}
          </tbody></table>
          <div class="ws-po-foot"><span>Our value <b>${ws.money(p.our_amount)}</b> <span class="ws-sub">(${ws.full(p.our_amount)})</span></span>
            ${printedDiffers ? `<span class="ws-sub">Total printed on the PO: ${ws.money(p.document_total)}, which includes lines for other parties</span>` : ''}</div>
          <div id="po-prev-${p.id}"></div>
        </div>`;
      }).join('')}</div>${this.fullPage('purchase-orders', 'Edit purchase orders')}`;
    },

    async poPreview(id) {
      const box = document.getElementById(`po-prev-${id}`);
      if (!box) return;
      box.innerHTML = '<div class="loading" style="padding:8px">Loading</div>';
      try {
        const p = await apiFetchRaw(`/purchase-orders/${id}/subtender-preview`);
        box.innerHTML = `<div class="ws-prev">
          ${(p.warnings || []).map(w => `<div class="ws-warn">${esc(w)}</div>`).join('')}
          <table class="tbl"><thead><tr><th>Line</th><th>Sub-tender</th><th class="r">Qty</th><th>Action</th></tr></thead><tbody>
          ${(p.rows || []).map(r => `<tr><td>${r.line}</td><td>${esc(r.tender_number || '—')}</td><td class="num r">${ws.qtl(r.qty_qtl)}</td>
            <td>${r.action === 'update' ? '<span class="pill pill-active">Exists</span>' : r.action === 'create' ? '<span class="pill pill-info">Will be created</span>' : '<span class="pill pill-pending">Needs a person</span>'}</td></tr>`).join('')}
          </tbody></table></div>`;
      } catch (e) { box.innerHTML = `<div class="ws-warn">Preview failed: ${esc(e.message)}</div>`; }
    },

    async loadDocs() {
      if (!this.docs) this.docs = await ws.get(`/workspace/rms/${this.id}/documents`);
      return this.docs;
    },

    async tab_inbox() {
      const docs = await this.loadDocs();
      const label = {
        purchase_order: 'Purchase order', tender_extension: 'Time extension', tender_notice: 'Tender notice',
        plant_unloading: 'Unloading sheet', rejection_notice: 'Rejection letter', purchase_bill: 'Purchase bill', not_classified: 'Not sorted',
      };
      const bills = this.data.bills_to_check || 0;
      return `
        ${bills ? `<div class="ws-note">${bills} bill${bills === 1 ? '' : 's'} of this RM waiting in Bill review. <button class="btn btn-xs" onclick="state.billFilter='pending';nav('bills')">Review bills →</button></div>` : ''}
        ${docs.length ? `<div class="ws-sub" style="margin-bottom:8px">Documents that came in by email or WhatsApp and mention ${esc(this.data.tender_code)}. Nothing from them is counted until they are approved.</div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Type</th><th>Document</th><th>Received</th><th>From</th><th></th></tr></thead><tbody>
        ${docs.map(x => `<tr>
          <td><span class="pill ${x.document_type === 'tender_extension' ? 'pill-info' : 'pill-muted'}">${esc(label[x.document_type] || x.document_type)}</span></td>
          <td><div>${esc(x.file_name)}</div>${x.plant_name ? `<div class="ws-sub">${esc(x.plant_name)}</div>` : ''}</td>
          <td>${ws.date(x.created_at)}</td><td class="ws-sub">${esc(x.source_address || x.source || '')}</td>
          <td style="white-space:nowrap">
            ${x.doc_url ? `<a class="btn btn-xs" href="${esc(x.doc_url)}" target="_blank" rel="noopener">Open</a>` : ''}
            ${x.document_type === 'tender_extension'
              ? `<input type="date" class="ws-inline-date" id="ext-${x.id}" value="${esc(x.extension?.new_end_date || '')}"> <button class="btn btn-xs btn-primary" onclick="pages.rm.applyExtension(${x.id})">Apply extension</button>`
              : `<button class="btn btn-xs" onclick="pages.rm.reviewDoc(${x.id})">Review</button>`}
          </td></tr>`).join('')}
        </tbody></table></div>` : this.emptyRow('Nothing waiting for this RM.')}
        ${this.fullPage('pending-ingests', 'Open the full Inbox')}`;
    },

    async reviewDoc(id) {
      nav('pending-ingests');
      setTimeout(() => pages['pending-ingests']?.preview?.(id), 300);
    },

    async applyExtension(pendingId) {
      const v = document.getElementById(`ext-${pendingId}`)?.value;
      if (!v) return toast('Enter the new last supply date from the order', 'warn');
      try {
        const r = await apiFetchRaw(`/main-tenders/${this.id}/extend`, { method: 'POST', body: JSON.stringify({ new_end_date: v, pending_id: pendingId }) });
        toast(r.changed?.length ? `Supply extended to ${ws.date(v)} for ${r.changed.length} sub-tender(s)` : 'Already at or past that date; marked as done', 'ok');
        this.load();
      } catch {}
    },

    async tab_bills() {
      const rows = await ws.get('/bills', { main_tender_id: this.id });
      if (!rows.length) return this.emptyRow('No purchase bills from brokers for this RM yet.') + this.fullPage('bills', 'Open Bill review');
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Bill</th><th>Date</th><th>Broker</th><th>Truck</th><th>Material</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th><th>Status</th></tr></thead><tbody>
        ${rows.map(b => `<tr class="ws-row" onclick="pages.rm.openBill(${b.id})"><td>${esc(b.bill_number || '#' + b.id)}</td><td>${ws.date(b.bill_date)}</td><td>${esc(b.broker_name)}</td>
          <td class="num">${esc(b.vehicle_number)}</td><td>${esc(b.material)}</td><td class="num r">${ws.qtl(b.qty_mt)}</td><td class="num r">${ws.full(b.rate_per_mt)}</td>
          <td class="num r">${ws.full(b.total_amount)}</td><td>${statusPill(b.status)}</td></tr>`).join('')}
        </tbody></table></div>${this.fullPage('bills', 'Open Bill review')}`;
    },

    openBill(id) {
      nav('bills');
      setTimeout(() => pages.bills?.select?.(id), 400);
    },

    async tab_dispatch() {
      const rows = await ws.get('/dispatches', { main_tender_id: this.id });
      if (!rows.length) return this.emptyRow('No trucks dispatched for this RM yet.') + this.fullPage('dispatch');
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Truck</th><th>Date</th><th>Plant</th><th>Material</th><th class="r">Qty</th><th class="r">Accepted</th><th class="r">Rejected</th><th>Status</th></tr></thead><tbody>
        ${rows.map(x => `<tr><td class="num">${esc(x.vehicle_number)}</td><td>${ws.date(x.dispatch_date)}</td><td>${esc(x.plant)}</td><td>${esc(x.material)}</td>
          <td class="num r">${ws.qtl(x.qty_mt)}</td><td class="num r">${x.accepted_mt !== null ? ws.qtl(x.accepted_mt) : '—'}</td><td class="num r">${x.rejected_mt ? ws.qtl(x.rejected_mt) : '—'}</td><td>${statusPill(x.status)}</td></tr>`).join('')}
        </tbody></table></div>${this.fullPage('dispatch')}`;
    },

    async tab_unloading() {
      const rows = await ws.get('/plant-unloading', { main_tender_id: this.id });
      if (!rows.length) {
        const waiting = (this.data.pending_docs_by_type || {}).plant_unloading || 0;
        return this.emptyRow(waiting ? `No unloading approved yet. ${waiting} unloading sheet${waiting === 1 ? ' is' : 's are'} waiting in “To check”.` : 'No plant unloading recorded for this RM yet.') + this.fullPage('plant-details');
      }
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Truck</th><th>WS no.</th><th>Plant</th><th>Item</th><th class="r">Bags</th><th class="r">Received</th><th class="r">Net</th><th>Status</th></tr></thead><tbody>
        ${rows.map(x => `<tr><td>${ws.date(x.entry_date)}</td><td class="num">${esc(x.truck_number)}</td><td>${esc(x.ws_no || '—')}</td><td>${esc(x.plant_name)}</td><td>${esc(x.item_name)}</td>
          <td class="num r">${x.no_of_bags ?? '—'}</td><td class="num r">${ws.qtl(x.received_qty_mt)}</td><td class="num r">${ws.qtl(x.net_qty_mt)}</td><td>${statusPill(x.status)}</td></tr>`).join('')}
        </tbody></table></div>${this.fullPage('plant-details')}`;
    },

    async tab_rejections() {
      const [rows, docs] = await Promise.all([ws.get('/receipts', { main_tender_id: this.id }), this.loadDocs()]);
      const rej = rows.filter(r => Number(r.rejected_mt) > 0);
      const letters = docs.filter(d => d.document_type === 'rejection_notice');
      return `${letters.length ? `<div class="ws-note">${letters.length} rejection letter${letters.length === 1 ? '' : 's'} waiting to be checked. <button class="btn btn-xs" onclick="pages.rm.setTab('inbox')">See them →</button></div>` : ''}
        ${rej.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Truck</th><th>Plant</th><th>Material</th><th class="r">Accepted</th><th class="r">Rejected</th><th>Reason</th></tr></thead><tbody>
        ${rej.map(x => `<tr><td>${ws.date(x.receipt_date)}</td><td class="num">${esc(x.vehicle_number)}</td><td>${esc(x.plant)}</td><td>${esc(x.material)}</td>
          <td class="num r">${ws.qtl(x.accepted_mt)}</td><td class="num r" style="color:var(--danger)">${ws.qtl(x.rejected_mt)}</td><td>${esc(x.rejection_reason || '—')}</td></tr>`).join('')}
        </tbody></table></div>` : this.emptyRow('No rejections recorded for this RM.')}${this.fullPage('receipts')}`;
    },

    async tab_sales() {
      const rows = await ws.get('/sales-bills', { main_tender_id: this.id });
      if (!rows.length) return this.emptyRow('No sales bills to the plant yet. They are made from approved unloading.') + this.fullPage('sales-bills', 'Make a sales bill');
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Sales bill</th><th>Date</th><th>Plant</th><th class="r">Qty</th><th class="r">Amount</th><th>Busy</th><th>Status</th></tr></thead><tbody>
        ${rows.map(x => `<tr><td>${esc(x.sb_number)}</td><td>${ws.date(x.bill_date)}</td><td>${esc(x.plant)}</td><td class="num r">${ws.qtl(x.qty_qtl ?? x.qty_mt)}</td>
          <td class="num r">${ws.full(x.total_amount)}</td><td>${x.busy_exported ? '<span class="pill pill-active">Sent</span>' : '<span class="pill pill-muted">Not sent</span>'}</td><td>${statusPill(x.status)}</td></tr>`).join('')}
        </tbody></table></div>${this.fullPage('sales-bills')}`;
    },

    async tab_payments() {
      const [pbs, pays] = await Promise.all([ws.get('/purchase-bills', { main_tender_id: this.id }), ws.get('/payments', { main_tender_id: this.id })]);
      const stateLabel = { awaiting_unloading: 'Waiting for plant result', nothing_due: 'Nothing due', overpaid: 'Overpaid, recover', unpaid: 'Unpaid', partly_paid: 'Part paid', paid: 'Paid' };
      return `<div class="ws-section-h">What we owe brokers <span class="ws-sub">accepted qty × deal rate</span></div>
        ${pbs.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Purchase bill</th><th>Date</th><th>Broker</th><th class="r">Payable</th><th class="r">Paid</th><th class="r">Balance</th><th>State</th></tr></thead><tbody>
        ${pbs.map(x => `<tr><td>${esc(x.pb_number)}</td><td>${ws.date(x.bill_date)}</td><td>${esc(x.broker)}</td><td class="num r">${ws.full(x.payable)}</td>
          <td class="num r">${ws.full(x.paid_amount)}</td><td class="num r">${ws.full(x.outstanding)}</td><td>${esc(stateLabel[x.payment_state] || x.payment_state)}</td></tr>`).join('')}
        </tbody></table></div>` : this.emptyRow('No purchase bills for this RM yet.')}
        <div class="ws-section-h" style="margin-top:18px">Payments made</div>
        ${pays.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Voucher</th><th>Date</th><th>Broker</th><th class="r">Amount</th><th>Mode</th><th>Ref</th><th>Status</th></tr></thead><tbody>
        ${pays.map(x => `<tr><td>${esc(x.voucher_number || '#' + x.id)}</td><td>${ws.date(x.payment_date)}</td><td>${esc(x.broker)}</td><td class="num r">${ws.full(x.amount)}</td>
          <td>${esc(x.payment_mode || '')}</td><td>${esc(x.reference_no || '')}</td><td>${statusPill(x.status)}</td></tr>`).join('')}
        </tbody></table></div>` : this.emptyRow('No payments recorded for this RM yet.')}
        ${this.fullPage('payments', 'Open Payments')}`;
    },
  };

  // ============================================================
  // GLOBAL SEARCH (Ctrl+K or /)
  // ============================================================
  const SECTION = {
    rms: 'Tenders (RM)', subtenders: 'Sub-tenders', purchase_orders: 'Purchase orders', bills: 'Bills',
    trucks: 'Dispatched trucks', unloading: 'Plant unloading', purchase_bills: 'Purchase bills',
    sales_bills: 'Sales bills', brokers: 'Brokers', documents: 'Inbox documents',
  };
  const TAB_FOR = { subtenders: 'overview', purchase_orders: 'pos', bills: 'bills', trucks: 'dispatch', unloading: 'unloading', purchase_bills: 'payments', sales_bills: 'sales' };
  let searchCtl = null, searchSeq = 0, searchItems = [], searchSel = 0, searchTimer = null;

  ws.openSearch = function (prefill) {
    let box = document.getElementById('ws-search');
    if (!box) {
      box = document.createElement('div');
      box.id = 'ws-search';
      box.className = 'ws-search-overlay';
      box.innerHTML = `<div class="ws-search-box" role="dialog" aria-label="Search">
        <div class="ws-search-input">
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>
          <input id="ws-search-q" placeholder="RM-844, PO number, truck RJ14…, bill no., broker" autocomplete="off">
          <label class="ws-search-scope"><input type="checkbox" id="ws-search-all"> All firms</label>
          <button class="btn btn-sm" onclick="ws.closeSearch()">Esc</button>
        </div>
        <div id="ws-search-res" class="ws-search-res"><div class="ws-sub" style="padding:14px">Type at least 2 letters.</div></div>
      </div>`;
      box.addEventListener('click', e => { if (e.target === box) ws.closeSearch(); });
      document.body.appendChild(box);
      const inp = box.querySelector('#ws-search-q');
      inp.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => ws.runSearch(inp.value), 220); });
      box.querySelector('#ws-search-all').addEventListener('change', () => ws.runSearch(inp.value));
      inp.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown') { e.preventDefault(); ws.moveSel(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); ws.moveSel(-1); }
        else if (e.key === 'Enter') { e.preventDefault(); if (searchItems[searchSel]) ws.pick(searchSel); }
        else if (e.key === 'Escape') ws.closeSearch();
      });
    }
    box.querySelector('#ws-search-all').checked = Boolean(state.globalView);
    box.classList.add('show');
    const inp = box.querySelector('#ws-search-q');
    if (typeof prefill === 'string' && prefill) {
      inp.value = prefill;
      box.querySelector('#ws-search-all').checked = true;
      ws.runSearch(prefill);
    }
    setTimeout(() => { inp.focus(); inp.select(); }, 10);
  };
  ws.closeSearch = function () { document.getElementById('ws-search')?.classList.remove('show'); };

  ws.runSearch = async function (q) {
    const res = document.getElementById('ws-search-res');
    q = (q || '').trim();
    if (q.length < 2) { res.innerHTML = '<div class="ws-sub" style="padding:14px">Type at least 2 letters.</div>'; searchItems = []; return; }
    if (searchCtl) searchCtl.abort();
    searchCtl = new AbortController();
    const seq = ++searchSeq;
    const allFirms = document.getElementById('ws-search-all')?.checked;
    res.innerHTML = '<div class="loading" style="padding:14px">Searching</div>';
    let data;
    try {
      const qs = new URLSearchParams({ q });
      if (!allFirms && state.context.companyId) qs.set('company_id', state.context.companyId);
      const r = await fetch(`${API}/search?${qs}`, { signal: searchCtl.signal, headers: { 'Content-Type': 'application/json' } });
      if (r.status === 401) { auth.show(); return; }
      if (!r.ok) throw new Error(`Search failed (${r.status})`);
      data = await r.json();
    } catch (e) {
      if (e.name === 'AbortError') return;
      if (seq === searchSeq) res.innerHTML = `<div class="ws-warn" style="margin:12px">${esc(e.message)}</div>`;
      return;
    }
    if (seq !== searchSeq) return;
    searchItems = [];
    let html = '';
    Object.keys(SECTION).forEach(sec => {
      const rows = data[sec] || [];
      if (!rows.length) return;
      html += `<div class="ws-search-sec">${SECTION[sec]}</div>`;
      rows.forEach(r => {
        const i = searchItems.length;
        searchItems.push({ sec, r });
        const firm = allFirms && r.company_id ? ` · ${esc(firmShort(firmName(r.company_id)))}` : '';
        html += `<button class="ws-search-item" data-i="${i}" onclick="ws.pick(${i})" onmousemove="ws.setSel(${i})">
          <span class="ws-search-label">${esc(r.label)}</span><span class="ws-sub">${esc(r.sub || '')}${firm}</span></button>`;
      });
    });
    searchSel = 0;
    res.innerHTML = html || `<div class="ws-sub" style="padding:14px">Nothing found for “${esc(q)}”.${allFirms ? '' : ' Tick “All firms” to look in the other firms too.'}</div>`;
    ws.setSel(0);
  };
  ws.setSel = function (i) {
    searchSel = i;
    document.querySelectorAll('#ws-search-res .ws-search-item').forEach(b => b.classList.toggle('sel', Number(b.dataset.i) === i));
  };
  ws.moveSel = function (d) {
    if (!searchItems.length) return;
    ws.setSel((searchSel + d + searchItems.length) % searchItems.length);
    document.querySelector(`#ws-search-res .ws-search-item[data-i="${searchSel}"]`)?.scrollIntoView({ block: 'nearest' });
  };
  ws.pick = async function (i) {
    const it = searchItems[i];
    if (!it) return;
    ws.closeSearch();
    const { sec, r } = it;
    if (sec === 'rms') return ws.openRm(r.id);
    if (sec === 'brokers') return nav('brokers');
    if (sec === 'documents') { nav('pending-ingests'); return setTimeout(() => pages['pending-ingests']?.preview?.(r.id), 300); }
    if (sec === 'bills' && !r.main_tender_id) { await ws.setFirm(r.company_id || null); nav('bills'); return setTimeout(() => pages.bills?.select?.(r.id), 400); }
    if (r.main_tender_id) return ws.openRm(r.main_tender_id, TAB_FOR[sec] || 'overview');
    toast('This record is not linked to an RM yet', 'warn');
  };

  document.addEventListener('keydown', e => {
    const tag = (e.target && e.target.tagName) || '';
    const typing = /INPUT|TEXTAREA|SELECT/.test(tag) || e.target?.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); ws.openSearch(); }
    else if (e.key === '/' && !typing) { e.preventDefault(); ws.openSearch(); }
  });
})();
