/* ============================================
   Stock Analyst Pro — frontend JS
   - theme toggle (light/dark)
   - 15-min auto-refresh
   - notification poll + popup modal w/ snooze
   ============================================ */
(function () {
  const REFRESH_MS = 15 * 60 * 1000;
  const NOTIF_POLL_MS = 60 * 1000;

  // ---------- THEME ----------
  const root = document.documentElement;
  const toggle = document.getElementById('themeToggle');
  if (toggle) {
    toggle.addEventListener('click', async () => {
      const cur = root.getAttribute('data-theme') || 'light';
      const next = cur === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try {
        await fetch('/api/theme', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ theme: next }),
        });
      } catch (e) { /* ignore */ }
      // soft reload to repaint TradingView widgets in new theme
      if (document.getElementById('tv_chart') || document.getElementById('tv_nifty')) {
        setTimeout(() => location.reload(), 200);
      }
    });
  }

  // ---------- NOTIFICATIONS ----------
  const bell = document.getElementById('notifBell');
  const dropdown = document.getElementById('notifDropdown');
  const countBadge = document.getElementById('notifCount');

  async function pollNotifications() {
    try {
      const r = await fetch('/api/notifications');
      const list = await r.json();
      const unseen = list.filter(n => !n.seen);
      if (countBadge) {
        if (unseen.length > 0) {
          countBadge.style.display = 'inline-block';
          countBadge.textContent = unseen.length;
        } else {
          countBadge.style.display = 'none';
        }
      }
      if (dropdown) {
        dropdown.innerHTML = list.length
          ? list.slice(0, 20).map(n => `
              <div class="notif-item ${n.severity}">
                <div class="nt-title">${n.title}</div>
                <div>${n.body}</div>
                <div class="nt-time">${(n.created_at || '').slice(0,16)}</div>
              </div>`).join('')
          : '<div class="notif-item">No notifications yet.</div>';
      }
      // pop critical not-yet-seen ones (skip snoozed)
      const now = new Date().toISOString();
      const popup = unseen.find(n =>
        n.severity === 'critical' &&
        (!n.snoozed_until || n.snoozed_until < now)
      );
      if (popup && !window.__shownPopupIds?.has(popup.id)) {
        showPopup(popup);
        window.__shownPopupIds = window.__shownPopupIds || new Set();
        window.__shownPopupIds.add(popup.id);
      }
    } catch (e) { /* ignore */ }
  }
  if (bell) {
    bell.addEventListener('click', (e) => {
      if (e.target.closest('.notif-dropdown')) return;
      dropdown.classList.toggle('show');
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#notifBell')) dropdown.classList.remove('show');
    });
    pollNotifications();
    setInterval(pollNotifications, NOTIF_POLL_MS);
  }

  // ---------- POPUP ----------
  const overlay = document.getElementById('popupModal');
  const pTitle = document.getElementById('popupTitle');
  const pBody = document.getElementById('popupBody');
  const pOk = document.getElementById('popupOk');
  const pSnooze = document.getElementById('popupSnooze');
  let currentPopupId = null;

  function showPopup(n) {
    if (!overlay) return;
    currentPopupId = n.id;
    pTitle.textContent = n.title || 'Alert';
    pBody.textContent = n.body || '';
    overlay.classList.remove('hidden');
  }
  if (pOk) {
    pOk.onclick = async () => {
      if (currentPopupId) {
        await fetch(`/api/notifications/seen/${currentPopupId}`, { method: 'POST' });
      }
      overlay.classList.add('hidden');
    };
  }
  if (pSnooze) {
    pSnooze.onclick = async () => {
      if (currentPopupId) {
        await fetch(`/api/notifications/snooze/${currentPopupId}`, { method: 'POST' });
      }
      overlay.classList.add('hidden');
    };
  }

  // ---------- 15-MIN AUTO-REFRESH (during live market) ----------
  let refreshTimer = null;
  function scheduleAutoRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      // soft reload — preserves scroll position via #hash if present
      location.reload();
    }, REFRESH_MS);
  }
  // only auto-refresh on dashboard/market/recommendations/best-picks/paper-trade
  const p = location.pathname;
  if (p === '/' || p.startsWith('/market') || p.startsWith('/recommendations')
      || p.startsWith('/best-picks') || p.startsWith('/paper-trade')) {
    scheduleAutoRefresh();
  }

  // ---------- DASHBOARD QUICK SCAN ----------
  window.runScan = async function (market, style) {
    const out = document.getElementById('scanResult');
    if (out) out.innerHTML = '<p class="muted">Scanning ' + market + ' / ' + style + '…</p>';
    const r = await fetch('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ market, style }),
    });
    const j = await r.json();
    if (!out) return;
    if (!j.results || j.results.length === 0) {
      out.innerHTML = '<p class="muted">No qualifying picks right now.</p>';
      return;
    }
    out.innerHTML = '<div class="reco-list">' + j.results.map(r => `
      <div class="reco-card ${r.side === 'BUY' ? 'pos' : 'neg'}">
        <div class="reco-head">
          <span class="r-tk"><a href="/stock/${encodeURIComponent(r.ticker)}">${r.ticker}</a></span>
          <span class="r-side">${r.side}</span>
          <span class="r-tier">${r.tier}</span>
          <span>Score <b>${r.score}</b>/10</span>
          <span>R:R <b>1:${r.rr_ratio}</b></span>
        </div>
        <div class="reco-grid">
          <div><span>Entry</span><b>${r.entry}</b></div>
          <div><span>T1</span><b>${r.target1}</b></div>
          <div><span>T2</span><b>${r.target2}</b></div>
          <div><span>SL</span><b>${r.stop_loss}</b></div>
        </div>
        <p>${r.rationale}</p>
      </div>`).join('') + '</div>';
  };
})();
