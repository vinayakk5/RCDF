
const API = 'http://localhost:8000/api';

// ── Global state ──────────────────────────────────────────────────────────
let state = {
  plants: [], materials: [], brokers: [], cycles: [],
  currentPage: 'dashboard',
  bills: [], selectedBill: null, billFilter: 'all',
  tenders: [], deals: [],
};

// ── Navigation ─────────────────────────────────────────────────────────────
function nav(page, el) {
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (el) el.classList.add('active');
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  state.currentPage = page;
  const titles = {
    dashboard: 'Dashboard', tenders: 'Tenders', deals: 'Deal Tracker',
    bills: 'Bill Review', dispatch: 'Dispatch Tracking',
    'purchase-bills': 'Purchase Bills', 'sales-bills': 'Sales Bills',
    payments: 'Payments', market: 'Market Prices', reports: 'Reports', brokers: 'Brokers'
  };
  document.getElementById('page-title').textContent = titles[page] || page;
  document.getElementById('topbar-actions').innerHTML = '';
  document.getElementById('topbar-sub').textContent = '';
  pages[page]?.load();
}

// ── API helpers ────────────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  try {
    const r = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    if (!r.ok) {
      const err = await r.text();
      throw new Error(err);
    }
    return await r.json();
  } catch (e) {
    toast(e.message || 'API error', 'err');
    throw e;
  }
}

async function apiPost(path, body) {
  return apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
}

async function apiPatch(path, body = {}) {
  return apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) });
}

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = '') {
  const el = document.getElementById('toast-el');
  el.textContent = msg;
  el.className = `toast show${type ? ' t-' + type : ''}`;
  clearTimeout(window._toast);
  window._toast = setTimeout(() => el.classList.remove('show'), 2500);
}

// ── Helpers ────────────────────────────────────────────────────────────────
function matClass(m) {
  return { Maize: 'mat-maize', Dorb: 'mat-dorb', Doms: 'mat-doms', 'Rice DDGS': 'mat-rice' }[m] || '';
}
function barColor(p) {
  return p >= 100 ? 'var(--success)' : p >= 60 ? 'var(--accent)' : p >= 35 ? 'var(--warn)' : 'var(--danger)';
}
function statusPill(s) {
  const map = {
    active: 'pill-active', pending: 'pill-pending', review: 'pill-pending',
    flagged: 'pill-danger', danger: 'pill-danger', at_risk: 'pill-pending',
    penalty_risk: 'pill-danger', done: 'pill-info', complete: 'pill-info',
    approved: 'pill-active', linked: 'pill-info', draft: 'pill-muted',
    confirmed: 'pill-active', paid: 'pill-info', sent: 'pill-active', partial: 'pill-pending',
    in_transit: 'pill-pending',
  };
  return `<span class="pill ${map[s] || 'pill-muted'}">${s?.replace('_', ' ')}</span>`;
}
function fmtAmt(v) { return v ? '₹' + parseFloat(v).toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'; }
function fmtMT(v) { return v ? parseFloat(v).toFixed(1) + ' Qtl' : '—'; }
function modal(html) { document.getElementById('modal-container').innerHTML = html; }
function closeModal() { document.getElementById('modal-container').innerHTML = ''; }

// ── Load reference data ────────────────────────────────────────────────────
async function loadRef() {
  try {
    [state.plants, state.materials, state.brokers, state.cycles] = await Promise.all([
      apiFetch('/plants'), apiFetch('/materials'), apiFetch('/brokers'), apiFetch('/cycles')
    ]);
    const active = state.cycles.find(c => c.is_active);
    if (active) {
      document.getElementById('footer-cycle').innerHTML =
        `<div>Sproxx cycle</div><div class="cycle-name">${active.name}</div>`;
      document.getElementById('topbar-sub').textContent = active.name;
    }
  } catch {}
}

// ============================================================
// DASHBOARD
// ============================================================
const pages = {};

pages.dashboard = {
  async load() {
    const el = document.getElementById('page-dashboard');
    el.innerHTML = '<div class="loading">Loading dashboard</div>';
    try {
      const d = await apiFetch('/dashboard');
      const t = d.tenders;
      el.innerHTML = `
        <div style="padding:20px">
          <div class="stats-grid" style="grid-template-columns:repeat(5,minmax(0,1fr))">
            <div class="stat-card">
              <div class="stat-n" style="color:var(--accent)">${t.tender_mt}</div>
              <div class="stat-l">Tender MT</div>
              <div class="stat-sub">${t.total} tenders</div>
            </div>
            <div class="stat-card">
              <div class="stat-n">${t.dispatched_mt}</div>
              <div class="stat-l">Dispatched MT</div>
              <div class="stat-sub">${Math.round(t.dispatched_mt/t.tender_mt*100)||0}% of total</div>
            </div>
            <div class="stat-card">
              <div class="stat-n" style="color:${barColor(t.accepted_pct)}">${t.accepted_mt}</div>
              <div class="stat-l">Accepted MT</div>
              <div class="stat-sub">${t.accepted_pct}% fulfilled</div>
            </div>
            <div class="stat-card">
              <div class="stat-n" style="color:var(--warn)">${t.at_risk}</div>
              <div class="stat-l">Items at risk</div>
              <div class="stat-sub">Below 50%</div>
            </div>
            <div class="stat-card">
              <div class="stat-n" style="color:var(--danger)">${t.penalty_risk}</div>
              <div class="stat-l">Penalty risk</div>
              <div class="stat-sub">Week-1 breach</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px">
            <div class="stat-card">
              <div class="stat-l" style="margin-bottom:8px">Bills by status</div>
              ${Object.entries(d.bills).map(([s,n])=>`
                <div class="chart-bar-row">
                  <div class="chart-bar-label">${s.replace('_',' ')}</div>
                  <div class="chart-bar-track"><div class="chart-bar-fill" style="width:${Math.min(n/Math.max(...Object.values(d.bills))*100,100)}%;background:${s==='pending'?'var(--warn)':s==='flagged'?'var(--danger)':s==='approved'||s==='linked'?'var(--success)':'var(--muted)'}"></div></div>
                  <div class="chart-bar-val">${n}</div>
                </div>`).join('')}
            </div>
            <div class="stat-card">
              <div class="stat-l" style="margin-bottom:8px">Financials</div>
              <div style="display:flex;flex-direction:column;gap:10px">
                <div>
                  <div style="font-size:10px;color:var(--muted);margin-bottom:3px">Pending broker payments</div>
                  <div class="stat-n" style="font-size:18px;color:var(--warn)">${fmtAmt(d.payments.pending_purchase)}</div>
                </div>
                <div>
                  <div style="font-size:10px;color:var(--muted);margin-bottom:3px">Outstanding from RCDF plants</div>
                  <div class="stat-n" style="font-size:18px;color:var(--info)">${fmtAmt(d.payments.outstanding_sales)}</div>
                </div>
              </div>
            </div>
          </div>
          <div class="sec-header">
            <div class="sec-title">Quick actions</div>
          </div>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button class="btn btn-primary" onclick="nav('bills',document.querySelector('[onclick*=bills]'))">Review pending bills (${d.bills.pending||0})</button>
            <button class="btn" onclick="nav('tenders',document.querySelector('[onclick*=tenders]'))">View tenders</button>
            <button class="btn" onclick="nav('reports',document.querySelector('[onclick*=reports]'))">Penalty risk report</button>
            <button class="btn" onclick="nav('market',document.querySelector('[onclick*=market]'))">Update market prices</button>
          </div>
        </div>`;
      // Update badge
      document.getElementById('nb-bills').textContent = d.bills.pending || 0;
    } catch (e) {
      el.innerHTML = `<div style="padding:20px;color:var(--danger)">Could not load dashboard. Is the backend running? <br><small>${e.message}</small></div>`;
    }
  }
};

// ============================================================
// TENDERS
// ============================================================
pages.tenders = {
  async load() {
    const el = document.getElementById('page-tenders');
    el.innerHTML = '<div class="loading">Loading tenders</div>';
    document.getElementById('topbar-actions').innerHTML =
      `<button class="btn btn-primary" onclick="pages.tenders.openAdd()">+ New tender</button>`;
    try {
      const tenders = await apiFetch('/tenders');
      state.tenders = tenders;
      if (!tenders.length) { el.innerHTML = '<div class="loading">No tenders yet. Create your first tender.</div>'; return; }
      el.innerHTML = tenders.map(t => {
        const s = t.summary;
        return `<div class="tender-block">
          <div class="tender-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none';this.querySelector('.th-caret').classList.toggle('open')">
            <span class="th-caret">&#9658;</span>
            <div style="flex:1">
              <div style="display:flex;align-items:center;gap:8px">
                <span style="font-family:var(--mono);font-size:11px;color:var(--muted)">${t.tender_number}</span>
                <span style="font-size:14px;font-weight:500">${t.plant} — ${t.material}</span>
                <span class="pill ${matClass(t.material)}">${t.material}</span>
                <button class="btn btn-xs" onclick="event.stopPropagation();pages.tenders.openEdit(${t.id})" style="margin-left:4px">Edit</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation();pages.tenders.deleteTender(${t.id})" style="border-color:var(--danger);color:var(--danger)">Delete</button>
              </div>
              <div style="font-size:11px;color:var(--muted);margin-top:2px">W1: ${t.week1_deadline} · W2: ${t.week2_deadline}</div>
            </div>
            <div style="text-align:right;margin-right:16px">
              <div class="num" style="color:${barColor(s.accepted_pct)}">${s.accepted_pct}%</div>
              <div style="font-size:10px;color:var(--muted)">${s.total_accepted_mt}/${t.tender_mt} Qtl</div>
              <div style="font-size:10px;color:var(--muted);margin-top:4px">Billed: ${s.total_billed_mt} Qtl · Remaining: ${s.bill_remaining_mt} Qtl</div>
            </div>
            ${statusPill(t.status)}
          </div>
          <div style="display:none">
            <table class="tbl">
              <thead><tr>
                <th>Broker</th><th class="r">Deal Qtl</th><th class="r">Dispatched</th>
                <th class="r">Accepted</th><th class="r">Rejected</th><th class="r">Billed</th><th class="r">Bill Remain</th><th>Status</th>
              </tr></thead>
              <tbody>
                ${t.deals.map(d=>`<tr>
                  <td>${d.broker}</td>
                  <td class="num r">${d.deal_mt} Qtl</td>
                  <td class="num r">${d.dispatched_mt}</td>
                  <td class="num r ok">${d.accepted_mt}</td>
                  <td class="num r ${d.rejected_mt>0?'danger':'muted'}">${d.rejected_mt||'—'}</td>
                  <td class="num r">${d.billed_mt !== undefined ? d.billed_mt : '—'}</td>
                  <td class="num r">${d.bill_remaining_mt !== undefined ? d.bill_remaining_mt : '—'}</td>
                  <td>${statusPill(d.status)}</td>
                </tr>`).join('')}
              </tbody>
            </table>
            <div style="padding:10px 14px;border-top:1px solid var(--border);display:flex;gap:8px">
              <button class="btn btn-sm" onclick="pages.deals.openAdd(${t.id})">+ Add deal</button>
              <div style="margin-left:auto">
                <div class="prog-wrap" style="min-width:200px">
                  <div class="prog-bar"><div class="prog-fill" style="width:${Math.min(s.accepted_pct,100)}%;background:${barColor(s.accepted_pct)}"></div></div>
                  <div class="prog-label"><span>W1: ${s.week1_pct}%</span><span class="hi">${s.accepted_pct}% overall</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>`;
      }).join('');
    } catch {}
  },

  openAdd() {
    const plants = state.plants.map(p=>`<option value="${p.id}">${p.name}</option>`).join('');
    const mats   = state.materials.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');
    const cycs   = state.cycles.map(c=>`<option value="${c.id}" ${c.is_active?'selected':''}>${c.name}</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">New tender <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Cycle</div><select class="form-select" id="tf-cycle">${cycs}</select></div>
            <div class="form-field"><div class="form-label">Tender number</div><input class="form-input" id="tf-num" placeholder="T-2403-07"></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Plant</div><select class="form-select" id="tf-plant">${plants}</select></div>
            <div class="form-field"><div class="form-label">Material</div><select class="form-select" id="tf-mat">${mats}</select></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Tender qty (MT)</div><input class="form-input" id="tf-mt" type="number" placeholder="1000"></div>
            <div class="form-field"><div class="form-label">Week 1 target (MT)</div><input class="form-input" id="tf-w1" type="number" placeholder="50"></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Week 1 deadline</div><input class="form-input" id="tf-d1" type="date"></div>
            <div class="form-field"><div class="form-label">Week 2 deadline</div><input class="form-input" id="tf-d2" type="date"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.tenders.save()">Create tender</button>
        </div>
      </div>
    </div>`);
  },

  async save() {
    const body = {
      cycle_id:        parseInt(document.getElementById('tf-cycle').value),
      tender_number:   document.getElementById('tf-num').value,
      plant_id:        parseInt(document.getElementById('tf-plant').value),
      material_id:     parseInt(document.getElementById('tf-mat').value),
      tender_mt:       parseFloat(document.getElementById('tf-mt').value),
      week1_target_mt: parseFloat(document.getElementById('tf-w1').value),
      week1_deadline:  document.getElementById('tf-d1').value,
      week2_deadline:  document.getElementById('tf-d2').value,
    };
    try {
      await apiPost('/tenders', body);
      closeModal(); toast('Tender created', 'ok');
      pages.tenders.load();
    } catch {}
  },

  openEdit(id) {
    const t = state.tenders.find(x => x.id === id);
    if (!t) return;
    const plants = state.plants.map(p=>`<option value="${p.id}" ${p.name===t.plant?'selected':''}>${p.name}</option>`).join('');
    const mats   = state.materials.map(m=>`<option value="${m.id}" ${m.name===t.material?'selected':''}>${m.name}</option>`).join('');
    const cycs   = state.cycles.map(c=>`<option value="${c.id}" ${c.is_active?'selected':''}>${c.name}</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Edit tender ${t.tender_number} <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Cycle</div><select class="form-select" id="tf-cycle">${cycs}</select></div>
            <div class="form-field"><div class="form-label">Tender number</div><input class="form-input" id="tf-num" value="${t.tender_number}"></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Plant</div><select class="form-select" id="tf-plant">${plants}</select></div>
            <div class="form-field"><div class="form-label">Material</div><select class="form-select" id="tf-mat">${mats}</select></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Tender qty (MT)</div><input class="form-input" id="tf-mt" type="number" value="${t.tender_mt}"></div>
            <div class="form-field"><div class="form-label">Week 1 target (MT)</div><input class="form-input" id="tf-w1" type="number" value="${t.week1_target_mt}"></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Week 1 deadline</div><input class="form-input" id="tf-d1" type="date" value="${t.week1_deadline}"></div>
            <div class="form-field"><div class="form-label">Week 2 deadline</div><input class="form-input" id="tf-d2" type="date" value="${t.week2_deadline}"></div>
          </div>
          <div class="form-field">
            <div class="form-label">Status</div>
            <select class="form-select" id="tf-status">
              ${['active','at_risk','penalty_risk','complete','cancelled'].map(s=>`<option value="${s}" ${t.status===s?'selected':''}>${s.replace('_',' ')}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.tenders.saveEdit(${id})">Save changes</button>
        </div>
      </div>
    </div>`);
  },

  async saveEdit(id) {
    const body = {
      cycle_id:        parseInt(document.getElementById('tf-cycle').value),
      tender_number:   document.getElementById('tf-num').value,
      plant_id:        parseInt(document.getElementById('tf-plant').value),
      material_id:     parseInt(document.getElementById('tf-mat').value),
      tender_mt:       parseFloat(document.getElementById('tf-mt').value),
      week1_target_mt: parseFloat(document.getElementById('tf-w1').value),
      week1_deadline:  document.getElementById('tf-d1').value,
      week2_deadline:  document.getElementById('tf-d2').value,
    };
    try {
      await apiFetch(`/tenders/${id}`, { method: 'PUT', body: JSON.stringify(body) });
      const status = document.getElementById('tf-status').value;
      await apiFetch(`/tenders/${id}/status?status=${status}`, { method: 'PATCH' });
      closeModal(); toast('Tender updated', 'ok');
      pages.tenders.load();
    } catch {}
  },

  async deleteTender(id) {
    if (!confirm('Cancel this tender and all its deals?')) return;
    try {
      await apiFetch(`/tenders/${id}`, { method: 'DELETE' });
      toast('Tender cancelled', 'ok');
      pages.tenders.load();
    } catch {}
  }
};

// ============================================================
// DEALS
// ============================================================
pages.deals = {
  async load() {
    const el = document.getElementById('page-deals');
    el.innerHTML = '<div class="loading">Loading deals</div>';
    document.getElementById('topbar-actions').innerHTML =
      `<button class="btn btn-primary" onclick="pages.deals.openAdd()">+ New deal</button>`;
    try {
      const deals = await apiFetch('/deals');
      if (!deals.length) { el.innerHTML = '<div class="loading">No deals yet.</div>'; return; }
      el.innerHTML = `<div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Deal no.</th><th>Tender</th><th>Broker</th><th>Material</th>
            <th class="r">Deal Qtl</th><th class="r">Rate</th><th class="r">Value</th>
            <th>Progress</th><th>Status</th><th></th>
          </tr></thead>
          <tbody>
            ${deals.map(d=>{
              const pct = Math.round(d.accepted_mt/d.deal_mt*100);
              return `<tr>
                <td class="num">${d.deal_number}</td>
                <td style="color:var(--muted);font-size:12px">T#${d.tender_id}</td>
                <td>${d.broker}</td>
                <td><span class="pill ${matClass(d.material)}">${d.material}</span></td>
                <td class="num r">${d.deal_mt} Qtl</td>
                <td class="num r">₹${parseFloat(d.rate_per_mt).toLocaleString('en-IN')}</td>
                <td class="num r">${fmtAmt(d.total_value)}</td>
                <td>
                  <div class="prog-wrap" style="min-width:120px">
                    <div class="prog-bar"><div class="prog-fill" style="width:${Math.min(pct,100)}%;background:${barColor(pct)}"></div></div>
                    <div class="prog-label"><span>${d.accepted_mt}/${d.deal_mt} MT</span><span class="hi">${pct}%</span></div>
                  </div>
                </td>
                <td>${statusPill(d.status)}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;
    } catch {}
  },

  openAdd(tenderId = null) {
    const tenderOpts = state.tenders.map(t=>
      `<option value="${t.id}" ${t.id===tenderId?'selected':''}>${t.tender_number} — ${t.plant} ${t.material}</option>`).join('');
    const brokerOpts = state.brokers.map(b=>`<option value="${b.id}">${b.name}</option>`).join('');
    const matOpts    = state.materials.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">New broker deal <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-field"><div class="form-label">Tender</div><select class="form-select" id="df-tender">${tenderOpts}</select></div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Broker</div><select class="form-select" id="df-broker">${brokerOpts}</select></div>
            <div class="form-field"><div class="form-label">Material</div><select class="form-select" id="df-mat">${matOpts}</select></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Deal qty (MT)</div><input class="form-input" id="df-mt" type="number"></div>
            <div class="form-field"><div class="form-label">Rate (₹/MT)</div><input class="form-input" id="df-rate" type="number"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.deals.save()">Create deal</button>
        </div>
      </div>
    </div>`);
  },

  async save() {
    const body = {
      tender_id:   parseInt(document.getElementById('df-tender').value),
      broker_id:   parseInt(document.getElementById('df-broker').value),
      material_id: parseInt(document.getElementById('df-mat').value),
      deal_mt:     parseFloat(document.getElementById('df-mt').value),
      rate_per_mt: parseFloat(document.getElementById('df-rate').value),
    };
    try {
      await apiPost('/deals', body);
      closeModal(); toast('Deal created', 'ok');
      pages.deals.load();
    } catch {}
  },

  openEdit(id) {
    const d = state.deals.find(x => x.id === id);
    if (!d) return;
    const brokerOpts = state.brokers.map(b=>`<option value="${b.id}" ${b.id===d.broker_id?'selected':''}>${b.name}</option>`).join('');
    const matOpts    = state.materials.map(m=>`<option value="${m.id}" ${m.name===d.material?'selected':''}>${m.name}</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Edit deal ${d.deal_number} <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Broker</div><select class="form-select" id="de-broker">${brokerOpts}</select></div>
            <div class="form-field"><div class="form-label">Material</div><select class="form-select" id="de-mat">${matOpts}</select></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Deal qty (MT)</div><input class="form-input" id="de-mt" type="number" value="${d.deal_mt}"></div>
            <div class="form-field"><div class="form-label">Rate (₹/MT)</div><input class="form-input" id="de-rate" type="number" value="${d.rate_per_mt}"></div>
          </div>
          <div class="form-field">
            <div class="form-label">Status</div>
            <select class="form-select" id="de-status">
              ${['active','partial','complete','cancelled'].map(s=>`<option value="${s}" ${d.status===s?'selected':''}>${s}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.deals.saveEdit(${id})">Save changes</button>
        </div>
      </div>
    </div>`);
  },

  async saveEdit(id) {
    try {
      await apiFetch(`/deals/${id}`, { method: 'PATCH', body: JSON.stringify({
        broker_id:   parseInt(document.getElementById('de-broker').value),
        material_id: parseInt(document.getElementById('de-mat').value),
        deal_mt:     parseFloat(document.getElementById('de-mt').value),
        rate_per_mt: parseFloat(document.getElementById('de-rate').value),
        status:      document.getElementById('de-status').value,
      })});
      closeModal(); toast('Deal updated', 'ok');
      state.deals = await apiFetch('/deals');
      pages.deals.load();
    } catch {}
  },

  async deleteDeal(id) {
    if (!confirm('Cancel this deal?')) return;
    try {
      await apiFetch(`/deals/${id}`, { method: 'DELETE' });
      toast('Deal cancelled', 'ok');
      state.deals = await apiFetch('/deals');
      pages.deals.load();
    } catch {}
  }
};

// ============================================================
// BILLS
// ============================================================
pages.bills = {
  async load() {
    await this.loadList();
    document.getElementById('topbar-actions').innerHTML = `
      <div style="display:flex;gap:6px">
        ${['all','pending','flagged','approved','linked'].map(f=>
          `<button class="btn btn-sm ${state.billFilter===f?'btn-primary':''}" onclick="pages.bills.filter('${f}')">${f}</button>`
        ).join('')}
      </div>
      <label class="btn" style="cursor:pointer">
        + Upload bill
        <input type="file" accept="image/*,.pdf" style="display:none" onchange="pages.bills.upload(this)">
      </label>`;
  },

  async loadList() {
    const el = document.getElementById('bills-list-panel');
    const url = state.billFilter === 'all' ? '/bills' : `/bills?status=${state.billFilter}`;
    try {
      const bills = await apiFetch(url);
      state.bills = bills;
      // Stats bar
      const counts = {};
      bills.forEach(b => { counts[b.status] = (counts[b.status]||0)+1; });
      el.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--border)">
          ${[['Pending',counts.pending||0,'warn'],['Flagged',counts.flagged||0,'danger'],['Approved',(counts.approved||0)+(counts.linked||0),'ok'],['Bills',bills.length,'info']].map(([l,n,c])=>
            `<div style="padding:10px;border-right:1px solid var(--border)">
              <div class="num ${c}" style="font-size:18px">${n}</div>
              <div style="font-size:10px;color:var(--muted)">${l}</div>
            </div>`).join('')}
        </div>
        <div style="padding:8px 10px;border-bottom:1px solid var(--border)">
          <input style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:6px 10px;color:var(--text);font-size:12px;outline:none"
            placeholder="Search broker, vehicle, material..."
            oninput="pages.bills.search(this.value)">
        </div>
        <div style="padding:6px 10px;border-bottom:1px solid var(--border);font-size:10px;color:var(--muted2);display:flex;justify-content:space-between">
          <span>Bills</span><span>${bills.length} shown</span>
        </div>
        <div id="bills-cards">
          ${bills.length ? bills.map(b => this.billCardHtml(b)).join('') : '<div style="padding:24px;text-align:center;color:var(--muted);font-size:12px">No bills</div>'}
        </div>`;
    } catch {}
  },

  billCardHtml(b) {
    const sel = state.selectedBill?.id === b.id;
    return `<div class="bill-card ${b.status} ${sel?'selected':''}" onclick="pages.bills.select(${b.id})">
      <div class="bc-top">
        <span class="bc-id">${b.id}</span>
        ${statusPill(b.status === 'review' ? 'pending' : b.status)}
      </div>
      <div class="bc-broker">${b.broker_name||'Unknown'}</div>
      <div class="bc-meta">
        <span>${b.material||'—'}</span>
        <span>${fmtMT(b.qty_mt)}</span>
        <span>${b.rate_per_mt?'₹'+parseFloat(b.rate_per_mt).toLocaleString('en-IN'):''}</span>
      </div>
      <div class="bc-src">
        <span class="src-dot ${b.source==='telegram'?'src-tg':'src-web'}"></span>
        ${b.source==='telegram'?'Telegram':'Web'} · ${b.vehicle_number||'<span style="color:var(--danger)">No vehicle</span>'} · ${b.bill_date||'—'}
      </div>
    </div>`;
  },

  async select(id) {
    state.selectedBill = state.bills.find(b => b.id === id);
    // Update list selection
    document.querySelectorAll('.bill-card').forEach(c => c.classList.remove('selected'));
    event?.currentTarget?.classList.add('selected');
    this.renderDetail(state.selectedBill);
  },

  renderDetail(b) {
    const panel = document.getElementById('bills-detail-panel');
    if (!b) return;
    const comp = b.qty_mt && b.rate_per_mt ? b.qty_mt * b.rate_per_mt : null;
    const amtOk = comp && b.total_amount && Math.abs(comp - b.total_amount) / b.total_amount < 0.05;
    const vehOk = b.vehicle_number && /^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$/i.test(b.vehicle_number.replace(/\s/g,''));
    const conf  = b.ocr_confidence ? Math.round(b.ocr_confidence * 100) : 0;
    const confColor = conf >= 85 ? 'var(--success)' : conf >= 65 ? 'var(--warn)' : 'var(--danger)';
    const deals = state.deals.filter(d => !b.material || d.material === b.material);

    panel.innerHTML = `
      <div class="detail-header">
        <div>
          <div style="font-family:var(--mono);font-size:11px;color:var(--muted)">Bill #${b.id} · ${b.source}</div>
          <div style="font-size:15px;font-weight:500">${b.broker_name||'Unknown broker'}</div>
        </div>
        <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
          ${b.status==='pending'||b.status==='flagged' ? `<button class="btn btn-sm btn-danger" onclick="pages.bills.reject(${b.id})">Reject</button>` : ''}
          ${b.status!=='approved'&&b.status!=='linked' ? `<button class="btn btn-sm btn-success" onclick="pages.bills.approve(${b.id})">Approve</button>` : ''}
          ${b.status==='approved' ? `<button class="btn btn-sm btn-primary" onclick="pages.bills.exportBusy(${b.id})">Export to Busy</button>` : ''}
          ${b.status==='linked' ? `<span style="color:var(--success);font-size:12px">✓ Linked</span>` : ''}
          <button class="btn btn-xs" onclick="pages.bills.deleteBill(${b.id})" style="border-color:var(--danger);color:var(--danger);margin-left:8px">🗑 Delete</button>
        </div>
      </div>
      <div class="detail-body">

        <div class="section-card">
          <div class="section-head">Bill preview
            <span style="margin-left:auto;font-size:10px;color:${b.is_handwritten?'var(--warn)':'var(--success)'}">
              ${b.is_handwritten?'Handwritten':'Printed'}</span>
          </div>
          <div style="padding:12px;background:var(--bg);display:flex;justify-content:center">
            ${b.image_path
              ? `<img src="/uploads/bills/${b.image_path.split('/').pop()}" style="max-width:320px;max-height:300px;border-radius:4px" onerror="this.replaceWith(document.createTextNode('Image not found'))">`
              : this.mockBillHtml(b)}
          </div>
        </div>

        <div class="section-card">
          <div class="section-head">
            Extracted fields
            <span class="pill ${b.ocr_source==='paddle'?'pill-active':'pill-pending'}" style="font-size:9px">${b.ocr_source||'manual'}</span>
            <div class="conf-bar-wrap">
              <span style="font-size:10px;color:var(--muted)">Confidence</span>
              <div class="conf-bar"><div class="conf-fill" style="width:${conf}%;background:${confColor}"></div></div>
              <span style="font-family:var(--mono);font-size:10px;color:${confColor}">${conf}%</span>
            </div>
          </div>
          <div class="fields-grid">
            ${this.fi('Vendor', 'broker_name', b.broker_name, false)}
            ${this.fi('Vehicle no.', 'vehicle_number', b.vehicle_number||'', !vehOk && b.vehicle_number)}
            ${this.fs('Material', 'material', b.material, state.materials.map(m=>m.name))}
            ${this.fi('Qty (Qtl)', 'qty_mt', b.qty_mt, false, true)}
            ${this.fi('Rate (₹/Qtl)', 'rate_per_mt', b.rate_per_mt, false, true)}
            ${this.fi('Total (₹)', 'total_amount', b.total_amount, !amtOk, true)}
            ${this.fi('Bill date', 'bill_date', b.bill_date, false)}
            ${this.fi('Bill no.', 'bill_number', b.bill_number||'', false)}
            ${this.fs('Plant', 'plant_name', b.plant, state.plants.map(p=>p.name))}
          </div>
          <div style="padding:10px 14px;border-top:1px solid var(--border)">
            <button class="btn btn-primary btn-sm" onclick="pages.bills.saveFields(${b.id})">Save corrections</button>
          </div>
        </div>

        <div class="section-card">
          <div class="section-head">Validation</div>
          <div class="val-row">
            <div class="val-item">
              <div class="val-dot ${amtOk?'val-ok':'val-fail'}"></div>
              <span class="val-text ${amtOk?'':'fail'}">Qty × Rate = Total</span>
              <span class="val-right">${comp?Math.round(comp).toLocaleString('en-IN'):'?'} vs ₹${b.total_amount?parseFloat(b.total_amount).toLocaleString('en-IN'):'?'}</span>
            </div>
            <div class="val-item">
              <div class="val-dot ${vehOk?'val-ok':b.vehicle_number?'val-fail':'val-warn'}"></div>
              <span class="val-text ${!vehOk&&b.vehicle_number?'fail':''}">Vehicle format (RJ XX XX XXXX)</span>
              <span class="val-right">${b.vehicle_number||'missing'}</span>
            </div>
            <div class="val-item">
              <div class="val-dot ${b.material?'val-ok':'val-fail'}"></div>
              <span class="val-text">Known material type</span>
              <span class="val-right">${b.material||'unknown'}</span>
            </div>
          </div>
        </div>

        <div class="section-card">
          <div class="section-head">Link to deal</div>
          <div style="padding:10px 14px">
            ${deals.length ? deals.map(d=>{
              const pct = Math.round(d.accepted_mt/d.deal_mt*100);
              const linked = b.deal_id === d.id;
              return `<div class="deal-opt ${linked?'linked':''}" onclick="pages.bills.linkDeal(${b.id},${d.id})">
                <div class="deal-radio"><div class="deal-radio-dot"></div></div>
                <div style="flex:1">
                  <div style="font-size:12px;font-weight:500">${d.deal_number} — ${d.broker}</div>
                  <div style="font-family:var(--mono);font-size:10px;color:var(--muted)">${d.material} · ${d.deal_mt - d.accepted_mt} MT remaining</div>
                </div>
                <div style="text-align:right">
                  <div class="deal-fill-bar"><div class="deal-fill-inner" style="width:${pct}%"></div></div>
                  <div style="font-family:var(--mono);font-size:9px;color:var(--muted)">${pct}% filled</div>
                </div>
              </div>`;
            }).join('') : '<div style="font-size:12px;color:var(--muted)">No matching deals. Create a deal first.</div>'}
          </div>
        </div>
      </div>`;
  },

  mockBillHtml(b) {
    return `<div class="bill-mock ${b.is_handwritten?'hw':''}">
      <div class="bm-head">${b.broker_name||'?'}</div>
      <div class="bm-row"><span>Material:</span><span>${b.material||'?'}</span></div>
      <div class="bm-row"><span>Qty:</span><span>${b.qty_mt||'?'} MT</span></div>
      <div class="bm-row"><span>Rate:</span><span>₹${b.rate_per_mt||'?'}/MT</span></div>
      <div class="bm-row"><span>Vehicle:</span><span>${b.vehicle_number||'?'}</span></div>
      <div class="bm-row"><span>Date:</span><span>${b.bill_date||'?'}</span></div>
      <div class="bm-total"><span>Total</span><span>${fmtAmt(b.total_amount)}</span></div>
      <div style="margin-top:8px;font-size:8px;text-align:center;color:#aaa">[${b.is_handwritten?'Handwritten':'Printed'} · OCR: ${b.ocr_source||'—'}]</div>
    </div>`;
  },

  fi(label, key, val, isErr, isMono = false) {
    return `<div class="field-row">
      <div class="field-label">${label}</div>
      <input class="field-input ${isErr?'err':''}" data-key="${key}" value="${val??''}"
        type="${isMono?'number':'text'}" step="${isMono?'0.01':'any'}" style="${isMono?'font-family:var(--mono)':''}">
    </div>`;
  },

  fs(label, key, val, opts) {
    const o = opts.map(op=>`<option ${op===val?'selected':''}>${op}</option>`).join('');
    return `<div class="field-row">
      <div class="field-label">${label}</div>
      <select class="field-sel" data-key="${key}"><option value="">— select —</option>${o}</select>
    </div>`;
  },

  async saveFields(billId) {
    const updates = {};
    document.querySelectorAll('[data-key]').forEach(el => {
      const k = el.dataset.key;
      if (['qty_mt','rate_per_mt','total_amount'].includes(k)) updates[k] = parseFloat(el.value)||null;
      else if (k === 'broker_name') updates.broker_name = el.value;
      else updates[k] = el.value || null;
    });
    try {
      const updated = await apiFetch(`/bills/${billId}`, { method: 'PATCH', body: JSON.stringify(updates) });
      state.selectedBill = updated;
      state.bills = state.bills.map(b => b.id === billId ? updated : b);
      this.renderDetail(updated);
      toast('Fields saved', 'ok');
    } catch {}
  },

  async approve(id) {
    try {
      const updated = await apiFetch(`/bills/${id}/approve`, { method: 'PATCH' });
      state.selectedBill = updated;
      state.bills = state.bills.map(b => b.id === id ? updated : b);
      this.renderDetail(updated);
      this.refreshCards();
      toast('Bill approved', 'ok');
    } catch {}
  },

  async reject(id) {
    try {
      const updated = await apiFetch(`/bills/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'flagged' }) });
      state.selectedBill = updated;
      state.bills = state.bills.map(b => b.id === id ? updated : b);
      this.renderDetail(updated);
      this.refreshCards();
      toast('Bill flagged');
    } catch {}
  },

  async linkDeal(billId, dealId) {
    try {
      const updated = await apiFetch(`/bills/${billId}/link/${dealId}`, { method: 'PATCH' });
      state.selectedBill = updated;
      state.bills = state.bills.map(b => b.id === billId ? updated : b);
      this.renderDetail(updated);
      toast('Linked to deal', 'ok');
    } catch {}
  },

  exportBusy(id) {
    toast('Generating Busy export...', 'ok');
  },

  async upload(input) {
    const file = input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('source', 'web');
    try {
      toast('Uploading and processing with OCR...');
      const r = await fetch(`${API}/bills/upload`, { method: 'POST', body: fd });
      const bill = await r.json();
      state.bills.unshift(bill);
      this.loadList();
      this.select(bill.id);
      toast('Bill processed', 'ok');
    } catch (e) { toast('Upload failed: ' + e.message, 'err'); }
  },

  filter(f) {
    state.billFilter = f;
    this.load();
  },

  search(q) {
    const ql = q.toLowerCase();
    document.querySelectorAll('.bill-card').forEach((card, i) => {
      const b = state.bills[i];
      const match = !ql || [b?.broker_name, b?.material, b?.vehicle_number, b?.plant].some(v => v?.toLowerCase().includes(ql));
      card.style.display = match ? '' : 'none';
    });
  },

  refreshCards() {
    const container = document.getElementById('bills-cards');
    if (container) container.innerHTML = state.bills.map(b => this.billCardHtml(b)).join('');
  },

  async deleteBill(id) {
    if (!confirm('Permanently delete this bill?')) return;
    try {
      await apiFetch(`/bills/${id}`, { method: 'DELETE' });
      state.bills = state.bills.filter(b => b.id !== id);
      state.selectedBill = null;
      document.getElementById('bills-detail-panel').innerHTML = `
        <div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--muted2);">
          <div style="font-size:13px">Bill deleted</div>
        </div>`;
      this.refreshCards();
      toast('Bill deleted', 'ok');
    } catch {}
  }
};

// ============================================================
// DISPATCH
// ============================================================
pages.dispatch = {
  async load() {
    const el = document.getElementById('page-dispatch');
    el.innerHTML = '<div class="loading">Loading dispatches</div>';
    document.getElementById('topbar-actions').innerHTML =
      `<div style="display:flex;gap:8px">
         <button class="btn btn-primary" onclick="pages.dispatch.openDispatch()">+ Add dispatch</button>
         <button class="btn" onclick="pages.dispatch.openReceipt()">+ Add plant receipt</button>
       </div>`;
    try {
      const dispatches = await apiFetch('/dispatches');
      if (!dispatches.length) { el.innerHTML = '<div class="loading">No dispatches yet.</div>'; return; }
      el.innerHTML = `<div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Vehicle</th><th>Date</th><th>Plant</th>
            <th class="r">Qty (Qtl)</th><th class="r">Accepted</th><th class="r">Rejected</th><th>Status</th>
          </tr></thead>
          <tbody>
            ${dispatches.map(d=>`<tr>
              <td class="num">${d.vehicle_number}</td>
              <td>${d.dispatch_date}</td>
              <td>${d.plant}</td>
              <td class="num r">${d.qty_mt}</td>
              <td class="num r ok">${d.accepted_mt??'—'}</td>
              <td class="num r ${d.rejected_mt>0?'danger':'muted'}">${d.rejected_mt||'—'}</td>
              <td>${statusPill(d.status)}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    } catch {}
  },

  openReceipt() {
    const plants = state.plants.map(p=>`<option value="${p.id}">${p.name}</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Record plant receipt <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Vehicle number</div><input class="form-input" id="rc-veh"></div>
            <div class="form-field"><div class="form-label">Receipt date</div><input class="form-input" type="date" id="rc-date"></div>
          </div>
          <div class="form-field"><div class="form-label">Plant</div><select class="form-select" id="rc-plant">${plants}</select></div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Accepted MT</div><input class="form-input" type="number" id="rc-acc" step="0.01"></div>
            <div class="form-field"><div class="form-label">Rejected MT</div><input class="form-input" type="number" id="rc-rej" step="0.01" value="0"></div>
          </div>
          <div class="form-field"><div class="form-label">Rejection reason (if any)</div><input class="form-input" id="rc-reason"></div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.dispatch.saveReceipt()">Save receipt</button>
        </div>
      </div>
    </div>`);
  },

  async saveReceipt() {
    const body = {
      vehicle_number: document.getElementById('rc-veh').value,
      receipt_date:   document.getElementById('rc-date').value,
      plant_id:       parseInt(document.getElementById('rc-plant').value),
      accepted_mt:    parseFloat(document.getElementById('rc-acc').value)||0,
      rejected_mt:    parseFloat(document.getElementById('rc-rej').value)||0,
      rejection_reason: document.getElementById('rc-reason').value||null,
    };
    try {
      await apiPost('/receipts', body);
      closeModal(); toast('Receipt saved', 'ok');
      pages.dispatch.load();
    } catch {}
  },

  openDispatch() {
    const plants = state.plants.map(p=>`<option value="${p.id}">${p.name}</option>`).join('');
    const deals = state.deals.map(d=>`<option value="${d.id}">${d.deal_number} — ${d.broker} (${d.deal_mt} Qtl)</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Record dispatch <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Vehicle number</div><input class="form-input" id="dc-veh"></div>
            <div class="form-field"><div class="form-label">Dispatch date</div><input class="form-input" type="date" id="dc-date"></div>
          </div>
          <div class="form-field"><div class="form-label">Plant</div><select class="form-select" id="dc-plant">${plants}</select></div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Qty (Qtl)</div><input class="form-input" type="number" id="dc-qty" step="0.01"></div>
            <div class="form-field"><div class="form-label">Deal (optional)</div><select class="form-select" id="dc-deal"><option value="">— none —</option>${deals}</select></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Driver name</div><input class="form-input" id="dc-driver"></div>
            <div class="form-field"><div class="form-label">Driver phone</div><input class="form-input" id="dc-phone"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.dispatch.saveDispatch()">Save dispatch</button>
        </div>
      </div>
    </div>`);
  },

  async saveDispatch() {
    const body = {
      vehicle_number: document.getElementById('dc-veh').value,
      dispatch_date:   document.getElementById('dc-date').value,
      plant_id:        parseInt(document.getElementById('dc-plant').value),
      qty_mt:          parseFloat(document.getElementById('dc-qty').value)||0,
      deal_id:         document.getElementById('dc-deal').value ? parseInt(document.getElementById('dc-deal').value) : null,
      driver_name:     document.getElementById('dc-driver').value || null,
      driver_phone:    document.getElementById('dc-phone').value || null,
    };
    try {
      await apiPost('/dispatches', body);
      closeModal(); toast('Dispatch recorded', 'ok');
      pages.dispatch.load();
    } catch (e) { }
  },
};

// ============================================================
// PURCHASE BILLS
// ============================================================
pages['purchase-bills'] = {
  async load() {
    const el = document.getElementById('page-purchase-bills');
    el.innerHTML = '<div class="loading">Loading</div>';
    document.getElementById('topbar-actions').innerHTML =
      `<button class="btn btn-primary" onclick="pages['purchase-bills'].exportSelected()">Export selected to Busy</button>`;
    try {
      const pbs = await apiFetch('/purchase-bills');
      if (!pbs.length) { el.innerHTML = '<div class="loading">No purchase bills yet. Approve bills first.</div>'; return; }
      let total = pbs.reduce((s,p)=>s+p.total_amount, 0);
      el.innerHTML = `
        <div class="stats-grid" style="grid-template-columns:repeat(3,1fr)">
          <div class="stat-card"><div class="stat-n">${pbs.length}</div><div class="stat-l">Total purchase bills</div></div>
          <div class="stat-card"><div class="stat-n" style="color:var(--warn)">${fmtAmt(pbs.filter(p=>p.status==='draft').reduce((s,p)=>s+p.total_amount,0))}</div><div class="stat-l">Pending payment</div></div>
          <div class="stat-card"><div class="stat-n" style="color:var(--success)">${fmtAmt(pbs.filter(p=>p.status==='paid').reduce((s,p)=>s+p.total_amount,0))}</div><div class="stat-l">Paid</div></div>
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr>
              <th><input type="checkbox" id="pb-all" onchange="document.querySelectorAll('.pb-chk').forEach(c=>c.checked=this.checked)"></th>
              <th>PB no.</th><th>Broker</th><th class="r">Qty (Qtl)</th>
              <th class="r">Rate</th><th class="r">Total</th><th>Date</th><th>Status</th><th></th>
            </tr></thead>
            <tbody>
              ${pbs.map(p=>`<tr>
                <td><input type="checkbox" class="pb-chk" value="${p.id}"></td>
                <td class="num">${p.pb_number}</td>
                <td>${p.broker}</td>
                <td class="num r">${p.qty_mt}</td>
                <td class="num r">₹${parseFloat(p.rate_per_mt).toLocaleString('en-IN')}</td>
                <td class="num r">${fmtAmt(p.total_amount)}</td>
                <td>${p.bill_date}</td>
                <td>${statusPill(p.status)}</td>
                <td style="display:flex;gap:4px">
                  ${p.status==='draft'?`<button class="btn btn-xs btn-primary" onclick="pages['purchase-bills'].pay(${p.id},${p.total_amount})">Pay</button>`:''}
                  ${p.status!=='paid'?`<button class="btn btn-xs" onclick="pages['purchase-bills'].deletePB(${p.id})" style="border-color:var(--danger);color:var(--danger)">Delete</button>`:''}
                </td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {}
  },

  async pay(id, amount) {
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Record payment <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Amount</div><input class="form-input" id="py-amt" type="number" value="${amount}"></div>
            <div class="form-field"><div class="form-label">Date</div><input class="form-input" id="py-date" type="date" value="${new Date().toISOString().slice(0,10)}"></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Mode</div>
              <select class="form-select" id="py-mode">
                <option>neft</option><option>rtgs</option><option>upi</option><option>cheque</option><option>cash</option>
              </select>
            </div>
            <div class="form-field"><div class="form-label">Ref no.</div><input class="form-input" id="py-ref"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-success" onclick="pages['purchase-bills'].doPayment(${id})">Confirm payment</button>
        </div>
      </div>
    </div>`);
  },

  async doPayment(id) {
    try {
      await apiPost('/payments', {
        purchase_bill_id: id,
        amount:      parseFloat(document.getElementById('py-amt').value),
        payment_date: document.getElementById('py-date').value,
        payment_mode: document.getElementById('py-mode').value,
        reference_no: document.getElementById('py-ref').value||null,
      });
      closeModal(); toast('Payment recorded', 'ok');
      this.load();
    } catch {}
  },

  exportSelected() {
    const ids = [...document.querySelectorAll('.pb-chk:checked')].map(c=>parseInt(c.value));
    if (!ids.length) { toast('Select bills to export'); return; }
    window.open(`${API}/export/purchase-bills`, '_blank');
    toast(`Exporting ${ids.length} bills to Busy CSV`, 'ok');
  },

  async deletePB(id) {
    if (!confirm('Cancel this purchase bill?')) return;
    try {
      await apiFetch(`/purchase-bills/${id}`, { method: 'DELETE' });
      toast('Purchase bill cancelled', 'ok');
      this.load();
    } catch {}
  }
};

// ============================================================
// SALES BILLS
// ============================================================
pages['sales-bills'] = {
  async load() {
    const el = document.getElementById('page-sales-bills');
    el.innerHTML = '<div class="loading">Loading</div>';
    try {
      const sbs = await apiFetch('/sales-bills');
      if (!sbs.length) { el.innerHTML = '<div class="loading">No sales bills yet.</div>'; return; }
      el.innerHTML = `<div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>SB no.</th><th>Plant</th><th class="r">Qty (Qtl)</th>
            <th class="r">Rate</th><th class="r">Total</th><th>Date</th><th>Status</th><th>Busy</th>
          </tr></thead>
          <tbody>
            ${sbs.map(s=>`<tr>
              <td class="num">${s.sb_number||'—'}</td>
              <td>${s.plant}</td>
              <td class="num r">${s.qty_mt}</td>
              <td class="num r">₹${parseFloat(s.rate_per_mt).toLocaleString('en-IN')}</td>
              <td class="num r">${fmtAmt(s.total_amount)}</td>
              <td>${s.bill_date}</td>
              <td>${statusPill(s.status)}</td>
              <td>${s.busy_exported?'<span class="pill pill-info" style="font-size:9px">Exported</span>':'—'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    } catch {}
  }
};

// ============================================================
// PAYMENTS
// ============================================================
pages.payments = {
  async load() {
    const el = document.getElementById('page-payments');
    el.innerHTML = '<div class="loading">Loading</div>';
    try {
      const pays = await apiFetch('/payments');
      if (!pays.length) { el.innerHTML = '<div class="loading">No payments yet.</div>'; return; }
      el.innerHTML = `<div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>Voucher no.</th><th>Broker</th><th class="r">Amount</th>
            <th>Date</th><th>Mode</th><th>Ref no.</th><th>Status</th><th>Busy</th><th></th>
          </tr></thead>
          <tbody>
            ${pays.map(p=>`<tr>
              <td class="num">${p.voucher_number||'—'}</td>
              <td>${p.broker}</td>
              <td class="num r">${fmtAmt(p.amount)}</td>
              <td>${p.payment_date||'—'}</td>
              <td><span class="pill pill-muted">${(p.payment_mode||'').toUpperCase()}</span></td>
              <td class="num" style="color:var(--muted)">${p.reference_no||'—'}</td>
              <td>${statusPill(p.status)}</td>
              <td>${p.busy_exported?'<span class="pill pill-info" style="font-size:9px">Exported</span>':'<button class="btn btn-xs" onclick="toast(\'Export to Busy\')">Export</button>'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    } catch {}
  }
};

// ============================================================
// MARKET PRICES
// ============================================================
pages.market = {
  async load() {
    const el = document.getElementById('page-market');
    el.innerHTML = '<div class="loading">Loading</div>';
    document.getElementById('topbar-actions').innerHTML =
      `<button class="btn btn-primary" onclick="pages.market.openAdd()">+ Add price</button>`;
    try {
      const prices = await apiFetch('/market-prices?days=30');
      // Group by material
      const byMat = {};
      prices.forEach(p => { (byMat[p.material]||=[]).push(p); });
      el.innerHTML = Object.entries(byMat).map(([mat, rows]) => {
        const latest = rows[rows.length-1];
        const first  = rows[0];
        const change = latest && first ? ((latest.price_per_mt - first.price_per_mt) / first.price_per_mt * 100).toFixed(1) : null;
        return `<div class="tbl-wrap" style="margin-bottom:16px">
          <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px">
            <span class="pill ${matClass(mat)}">${mat}</span>
            ${latest?`<span class="num" style="font-size:16px">₹${parseFloat(latest.price_per_mt).toLocaleString('en-IN')}/MT</span>`:''}
            ${change!==null?`<span style="font-size:12px;color:${parseFloat(change)>=0?'var(--danger)':'var(--success)'}">${parseFloat(change)>=0?'+':''}${change}% (30d)</span>`:''}
          </div>
          <table class="tbl">
            <thead><tr><th>Date</th><th>Market</th><th class="r">Price/MT</th><th>Source</th><th></th></tr></thead>
            <tbody>
              ${rows.slice(-10).reverse().map(p=>`<tr>
                <td>${p.price_date}</td>
                <td>${p.market||'—'}</td>
                <td class="num r">₹${parseFloat(p.price_per_mt).toLocaleString('en-IN')}</td>
                <td><span class="pill pill-muted">${p.source}</span></td>
                <td><button class="btn btn-xs" onclick="pages.market.deletePrice(${p.id})" style="border-color:var(--danger);color:var(--danger)">Delete</button></td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
      }).join('') || '<div class="loading">No market prices yet. Add some to help with tender bidding.</div>';
    } catch {}
  },

  openAdd() {
    const mats = state.materials.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Add market price <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-field"><div class="form-label">Material</div><select class="form-select" id="mp-mat">${mats}</select></div>
            <div class="form-field"><div class="form-label">Date</div><input class="form-input" type="date" id="mp-date" value="${new Date().toISOString().slice(0,10)}"></div>
          </div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Price (₹/MT)</div><input class="form-input" type="number" id="mp-price"></div>
            <div class="form-field"><div class="form-label">Market / mandi</div><input class="form-input" id="mp-market" placeholder="Jodhpur Mandi"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.market.save()">Save</button>
        </div>
      </div>
    </div>`);
  },

  async save() {
    try {
      await apiPost('/market-prices', {
        material_id:  parseInt(document.getElementById('mp-mat').value),
        price_date:   document.getElementById('mp-date').value,
        price_per_mt: parseFloat(document.getElementById('mp-price').value),
        market:       document.getElementById('mp-market').value||null,
      });
      closeModal(); toast('Price saved', 'ok');
      this.load();
    } catch {}
  },

  async deletePrice(id) {
    if (!confirm('Delete this price entry?')) return;
    try {
      await apiFetch(`/market-prices/${id}`, { method: 'DELETE' });
      toast('Price deleted', 'ok');
      this.load();
    } catch {}
  }
};

// ============================================================
// REPORTS
// ============================================================
pages.reports = {
  async load() {
    const el = document.getElementById('page-reports');
    el.innerHTML = '<div class="loading">Loading reports</div>';
    try {
      const [penalty, brokers] = await Promise.all([
        apiFetch('/reports/penalty-risk'),
        apiFetch('/reports/broker-performance'),
      ]);
      el.innerHTML = `
        <div style="margin-bottom:16px">
          <div class="sec-header"><div class="sec-title">Penalty risk report</div></div>
          ${penalty.length ?
            `<div class="alert-bar"><div class="alert-dot"></div><span style="color:var(--danger)">${penalty.length} items at risk of week-1 penalty</span></div>` +
            `<div class="tbl-wrap"><table class="tbl">
              <thead><tr><th>Tender</th><th>Plant</th><th>Material</th><th class="r">Target MT</th><th class="r">Accepted MT</th><th class="r">Shortfall</th><th>W1 %</th><th>Deadline</th><th class="r">Est. penalty</th></tr></thead>
              <tbody>${penalty.map(p=>`<tr>
                <td class="num">${p.tender_number}</td>
                <td>${p.plant}</td>
                <td><span class="pill ${matClass(p.material)}">${p.material}</span></td>
                <td class="num r">${p.week1_target_mt}</td>
                <td class="num r ${p.week1_pct>=100?'ok':'warn'}">${p.accepted_mt}</td>
                <td class="num r ${p.shortfall_mt>0?'danger':'ok'}">${p.shortfall_mt||'✓'}</td>
                <td>
                  <div class="prog-wrap" style="min-width:100px">
                    <div class="prog-bar"><div class="prog-fill" style="width:${Math.min(p.week1_pct,100)}%;background:${barColor(p.week1_pct)}"></div></div>
                    <div class="prog-label"><span class="hi">${p.week1_pct}%</span></div>
                  </div>
                </td>
                <td>${p.week1_deadline}</td>
                <td class="num r danger">${fmtAmt(p.estimated_penalty)}</td>
              </tr>`).join('')}</tbody>
            </table></div>`
            : '<div style="padding:14px;color:var(--success);font-size:13px">✓ No penalty risk items</div>'}
        </div>

        <div>
          <div class="sec-header"><div class="sec-title">Broker performance</div></div>
          <div class="tbl-wrap"><table class="tbl">
            <thead><tr><th>Broker</th><th class="r">Deals</th><th class="r">Deal Qtl</th><th class="r">Accepted</th><th class="r">Rejected</th><th>Fulfillment</th><th class="r">Rejection rate</th></tr></thead>
            <tbody>${brokers.map(b=>`<tr>
              <td>${b.broker}</td>
              <td class="num r">${b.deals}</td>
              <td class="num r">${b.deal_mt}</td>
              <td class="num r ok">${b.accepted_mt}</td>
              <td class="num r ${b.rejected_mt>0?'danger':'muted'}">${b.rejected_mt||'—'}</td>
              <td>
                <div class="prog-wrap" style="min-width:100px">
                  <div class="prog-bar"><div class="prog-fill" style="width:${b.fulfillment_pct}%;background:${barColor(b.fulfillment_pct)}"></div></div>
                  <div class="prog-label"><span class="hi">${b.fulfillment_pct}%</span></div>
                </div>
              </td>
              <td class="num r ${b.rejection_rate>5?'warn':'muted'}">${b.rejection_rate}%</td>
            </tr>`).join('')}</tbody>
          </table></div>
        </div>`;
    } catch {}
  }
};

// ============================================================
// BROKERS
// ============================================================
pages.brokers = {
  async load() {
    const el = document.getElementById('page-brokers');
    el.innerHTML = '<div class="loading">Loading</div>';
    document.getElementById('topbar-actions').innerHTML =
      `<button class="btn btn-primary" onclick="pages.brokers.openAdd()">+ Add broker</button>`;
    try {
      const brokers = await apiFetch('/brokers');
      if (!brokers.length) { el.innerHTML = '<div class="loading">No brokers yet.</div>'; return; }
      el.innerHTML = `<div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Name</th><th>Phone</th><th>Telegram chat ID</th><th></th></tr></thead>
          <tbody>
            ${brokers.map(b=>`<tr>
              <td>${b.name}</td>
              <td class="num">${b.phone||'—'}</td>
              <td class="num ${b.telegram_chat_id?'ok':'muted'}">${b.telegram_chat_id||'Not linked'}</td>
              <td style="display:flex;gap:4px">
                <button class="btn btn-xs" onclick="pages.brokers.openEdit(${b.id},'${b.name}','${b.phone||''}','${b.telegram_chat_id||''}')">Edit</button>
                <button class="btn btn-xs" onclick="pages.brokers.deleteBroker(${b.id})" style="border-color:var(--danger);color:var(--danger)">Delete</button>
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    } catch {}
  },

  openAdd() {
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Add broker <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-field"><div class="form-label">Name</div><input class="form-input" id="br-name"></div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Phone</div><input class="form-input" id="br-phone"></div>
            <div class="form-field"><div class="form-label">GSTIN</div><input class="form-input" id="br-gstin"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.brokers.save()">Save</button>
        </div>
      </div>
    </div>`);
  },

  async save() {
    try {
      await apiPost('/brokers', {
        name:  document.getElementById('br-name').value,
        phone: document.getElementById('br-phone').value||null,
        gstin: document.getElementById('br-gstin').value||null,
      });
      closeModal(); toast('Broker added', 'ok');
      await loadRef();
      this.load();
    } catch {}
  },

  openEdit(id, name, phone, tgid) {
    modal(`<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">Edit broker <button class="btn btn-sm" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div class="form-field"><div class="form-label">Name</div><input class="form-input" id="be-name" value="${name}"></div>
          <div class="form-row">
            <div class="form-field"><div class="form-label">Phone</div><input class="form-input" id="be-phone" value="${phone}"></div>
            <div class="form-field"><div class="form-label">Telegram chat ID</div><input class="form-input" id="be-tg" value="${tgid}" placeholder="Leave blank if not on Telegram"></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" onclick="closeModal()">Cancel</button>
          <button class="btn btn-primary" onclick="pages.brokers.saveEdit(${id})">Save changes</button>
        </div>
      </div>
    </div>`);
  },

  async saveEdit(id) {
    try {
      await apiFetch(`/brokers/${id}`, { method: 'PATCH', body: JSON.stringify({
        name:  document.getElementById('be-name').value,
        phone: document.getElementById('be-phone').value||null,
        telegram_chat_id: document.getElementById('be-tg').value||null,
      })});
      closeModal(); toast('Broker updated', 'ok');
      await loadRef();
      this.load();
    } catch {}
  },

  async deleteBroker(id) {
    if (!confirm('Remove this broker?')) return;
    try {
      await apiFetch(`/brokers/${id}`, { method: 'DELETE' });
      toast('Broker removed', 'ok');
      await loadRef();
      this.load();
    } catch {}
  }
,

  async deletePayment(id) {
    if (!confirm('Delete this payment record? This will revert the purchase bill status.')) return;
    try {
      await apiFetch(`/payments/${id}`, { method: 'DELETE' });
      toast('Payment deleted', 'ok');
      this.load();
    } catch {}
  }
};

// ── Boot ───────────────────────────────────────────────────────────────────
(async () => {
  await loadRef();
  // Load deals for bill linker
  try { state.deals = await apiFetch('/deals'); } catch {}
  pages.dashboard.load();
})();
