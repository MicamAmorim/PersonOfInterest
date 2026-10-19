(() => {
  if (window.__poiV55Loaded || typeof setView !== 'function') return;
  window.__poiV55Loaded = true;

  const baseSetView = setView;
  const mobilePrimary = new Set(['dashboard', 'cameras', 'timeline', 'identity']);
  let analyticsData = null;

  const icon = name => ({
    home: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H4.5A1.5 1.5 0 0 1 3 19.5z"/></svg>',
    camera: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>',
    timeline: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>',
    people: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.5-4 2.5-6 5.5-6s5 2 5.5 6"/><circle cx="17" cy="9" r="2.2"/><path d="M15.5 14c3.1-.5 5 1.2 5.5 4"/></svg>',
    more: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="1.8"/><circle cx="18" cy="6" r="1.8"/><circle cx="6" cy="18" r="1.8"/><circle cx="18" cy="18" r="1.8"/></svg>',
    chart: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5M4 19h16"/><path d="m7 15 4-4 3 2 5-6"/></svg>',
    bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 10a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20h4"/></svg>',
    settings: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></svg>',
    mic: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/></svg>',
    install: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M8 11l4 4 4-4M5 20h14"/></svg>'
  }[name] || '');

  function installViews() {
    const main = document.querySelector('main.main');
    const settings = document.getElementById('settingsView');
    if (!main || !settings) return false;

    if (!document.getElementById('analyticsView')) {
      const view = document.createElement('section');
      view.id = 'analyticsView';
      view.className = 'view poi-analytics-view';
      view.innerHTML = `
        <div class="poi-analytics-head">
          <div><p class="eyebrow">INTELIGÊNCIA · HISTÓRICO LOCAL</p><h2>Dashboard</h2><p class="muted paragraph">Fluxo, rotina e padrões derivados somente dos eventos já armazenados.</p></div>
          <div class="poi-analytics-controls"><select id="analyticsDays" aria-label="Período"><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option><option value="180">180 dias</option></select><button class="button ghost small" id="analyticsRefresh">↻ Atualizar</button></div>
        </div>
        <div id="analyticsBody"><div class="panel"><p class="muted">Carregando análise…</p></div></div>`;
      main.insertBefore(view, settings);
    }

    if (!document.getElementById('moreView')) {
      const view = document.createElement('section');
      view.id = 'moreView';
      view.className = 'view poi-more-view';
      view.innerHTML = `
        <div class="poi-more-intro"><p class="eyebrow">PERSONOFINTEREST</p><h2>Mais</h2><p class="muted paragraph">Inteligência, automações e configurações ficam organizadas aqui.</p></div>
        <div class="poi-more-grid">
          <button class="poi-more-card" data-more-view="analytics"><span class="poi-more-icon">${icon('chart')}</span><span><strong>Dashboard</strong><small>Gráficos, mapas de calor e padrões de rotina</small></span><b>›</b></button>
          <button class="poi-more-card" data-more-view="alerts"><span class="poi-more-icon">${icon('bell')}</span><span><strong>Alertas e automações</strong><small>Push, campainha, regras espaciais e Tonho</small></span><b>›</b></button>
          <button class="poi-more-card" data-more-view="settings"><span class="poi-more-icon">${icon('settings')}</span><span><strong>Sistema</strong><small>Serviços, sincronização e informações da instalação</small></span><b>›</b></button>
          <a class="poi-more-card" href="/tonho-lab.html"><span class="poi-more-icon">${icon('mic')}</span><span><strong>Tonho Lab</strong><small>Teste voz, comandos e diagnóstico do assistente</small></span><b>›</b></a>
          <button class="poi-more-card" id="moreInstallApp"><span class="poi-more-icon">${icon('install')}</span><span><strong>Instalar aplicativo</strong><small>Adicionar o PersonOfInterest à tela inicial</small></span><b>›</b></button>
        </div>`;
      main.insertBefore(view, settings);
    }

    const nav = document.querySelector('.sidebar nav');
    const alertsNav = nav?.querySelector('[data-view="alerts"]');
    if (nav && !nav.querySelector('[data-view="analytics"]')) {
      const button = document.createElement('button');
      button.className = 'nav-item poi-desktop-analytics-nav';
      button.dataset.view = 'analytics';
      button.innerHTML = '<span>▥</span> Dashboard';
      nav.insertBefore(button, alertsNav || nav.querySelector('[data-view="settings"]') || null);
      button.addEventListener('click', () => setView('analytics'));
    }

    document.getElementById('analyticsRefresh')?.addEventListener('click', loadAnalytics);
    document.getElementById('analyticsDays')?.addEventListener('change', loadAnalytics);
    document.querySelectorAll('[data-more-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.moreView)));
    document.getElementById('moreInstallApp')?.addEventListener('click', () => document.getElementById('pwaInstallBtn')?.click());
    return true;
  }

  function installBottomNav() {
    if (document.getElementById('poiMobileNav')) return;
    const nav = document.createElement('nav');
    nav.id = 'poiMobileNav';
    nav.className = 'poi-mobile-nav';
    nav.setAttribute('aria-label', 'Navegação principal');
    nav.innerHTML = [
      ['dashboard', 'home', 'Início'],
      ['cameras', 'camera', 'Câmeras'],
      ['timeline', 'timeline', 'Timeline'],
      ['identity', 'people', 'Pessoas'],
      ['more', 'more', 'Mais'],
    ].map(([view, glyph, label]) => `<button type="button" data-mobile-view="${view}"><span>${icon(glyph)}</span><small>${label}</small></button>`).join('');
    document.body.appendChild(nav);
    nav.querySelectorAll('[data-mobile-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.mobileView)));
  }

  function secondaryParent(view) {
    return ['analytics', 'alerts', 'settings', 'more'].includes(view) ? 'more' : view;
  }

  function syncNavigation(view) {
    const activeMobile = secondaryParent(view);
    document.querySelectorAll('#poiMobileNav [data-mobile-view]').forEach(button => button.classList.toggle('active', button.dataset.mobileView === activeMobile));
    document.body.dataset.poiView = view;
  }

  setView = function(view) {
    if (!['analytics', 'more'].includes(view)) {
      baseSetView(view);
      syncNavigation(view);
      return;
    }
    state.view = view;
    document.getElementById('pageTitle').textContent = view === 'analytics' ? 'Dashboard' : 'Mais';
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.getElementById(`${view}View`)?.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
    syncNavigation(view);
    if (view === 'analytics') loadAnalytics();
  };

  function number(value) {
    return new Intl.NumberFormat('pt-BR').format(Number(value || 0));
  }

  function seconds(value) {
    if (value == null) return '—';
    const secondsValue = Number(value);
    if (secondsValue < 60) return `${Math.round(secondsValue)} s`;
    const minutes = Math.floor(secondsValue / 60);
    const rest = Math.round(secondsValue % 60);
    return rest ? `${minutes}m ${rest}s` : `${minutes} min`;
  }

  function pct(value, total) {
    return total ? Math.round(Number(value || 0) / total * 100) : 0;
  }

  function lineChart(data) {
    const values = data.map(item => Number(item.total || 0));
    const max = Math.max(1, ...values);
    const width = 720;
    const height = 190;
    const pad = 12;
    const points = values.map((value, index) => {
      const x = pad + (width - pad * 2) * (index / Math.max(1, values.length - 1));
      const y = height - pad - (height - pad * 2) * (value / max);
      return [x, y];
    });
    const polyline = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const area = points.length ? `${pad},${height - pad} ${polyline} ${width - pad},${height - pad}` : '';
    const labels = data.filter((_, index) => index === 0 || index === data.length - 1 || index % Math.max(1, Math.floor(data.length / 5)) === 0);
    return `<div class="poi-line-chart"><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Fluxo diário"><defs><linearGradient id="poiArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#61dafb" stop-opacity=".28"/><stop offset="1" stop-color="#61dafb" stop-opacity="0"/></linearGradient></defs><polygon points="${area}" fill="url(#poiArea)"/><polyline points="${polyline}" fill="none" stroke="#61dafb" stroke-width="3" vector-effect="non-scaling-stroke"/></svg><div class="poi-chart-labels">${labels.map(item => `<span>${escapeHtml(item.label)}</span>`).join('')}</div></div>`;
  }

  function heatmap(map) {
    const cells = new Map((map.cells || []).map(cell => [`${cell.weekday}:${cell.hour}`, Number(cell.count || 0)]));
    const max = Math.max(1, Number(map.max || 0));
    const hours = Array.from({ length: 24 }, (_, hour) => hour);
    return `<div class="poi-heatmap-scroll"><div class="poi-heatmap"><div></div>${hours.map(hour => `<span class="poi-heat-hour">${hour % 3 === 0 ? `${hour}h` : ''}</span>`).join('')}${(map.weekdays || []).map((day, weekday) => `<span class="poi-heat-day">${escapeHtml(day)}</span>${hours.map(hour => { const count = cells.get(`${weekday}:${hour}`) || 0; const alpha = count ? .15 + .85 * count / max : .04; return `<i title="${escapeHtml(day)} ${hour}:00 · ${count} evento(s)" style="--heat:${alpha.toFixed(3)}"><b>${count || ''}</b></i>`; }).join('')}`).join('')}</div></div>`;
  }

  function bars(items, valueKey = 'count', limit = 8) {
    const shown = (items || []).slice(0, limit);
    const max = Math.max(1, ...shown.map(item => Number(item[valueKey] || 0)));
    return shown.length ? `<div class="poi-bars">${shown.map(item => `<div class="poi-bar-row"><span>${escapeHtml(item.name || item.label || '—')}</span><div><i style="width:${Number(item[valueKey] || 0) / max * 100}%"></i></div><b>${number(item[valueKey])}</b></div>`).join('')}</div>` : '<p class="muted">Ainda não há dados suficientes.</p>';
  }

  function renderAnalytics() {
    const data = analyticsData;
    const root = document.getElementById('analyticsBody');
    if (!root || !data) return;
    const s = data.summary || {};
    const identityTotal = Number(s.known || 0) + Number(s.probable || 0) + Number(s.unknown || 0);
    const peak = s.peak_hour == null ? '—' : `${String(s.peak_hour).padStart(2, '0')}:00`;
    root.innerHTML = `
      <div class="poi-analytics-stats">
        <article><span>Passagens</span><strong>${number(s.events)}</strong><small>${data.window_days} dias</small></article>
        <article><span>Conhecidos</span><strong>${pct(s.known, identityTotal)}%</strong><small>${number(s.unique_known)} pessoa(s)</small></article>
        <article><span>Pico</span><strong>${peak}</strong><small>${escapeHtml(s.busiest_weekday || 'sem padrão')}</small></article>
        <article><span>Duração mediana</span><strong>${seconds(s.median_duration_seconds)}</strong><small>por passagem</small></article>
      </div>

      <div class="poi-analytics-grid poi-analytics-grid-wide">
        <article class="panel poi-chart-panel"><div class="poi-panel-title"><div><p class="eyebrow">FLUXO</p><h3>Movimento diário</h3></div><span>${number(s.events)} eventos</span></div>${lineChart(data.daily || [])}</article>
        <article class="panel poi-chart-panel"><div class="poi-panel-title"><div><p class="eyebrow">IDENTIDADE</p><h3>Quem passa por aqui?</h3></div></div><div class="poi-composition"><div class="known" style="width:${pct(s.known, identityTotal)}%"></div><div class="probable" style="width:${pct(s.probable, identityTotal)}%"></div><div class="unknown" style="width:${pct(s.unknown, identityTotal)}%"></div></div><div class="poi-composition-legend"><span><i class="known"></i>Conhecidos <b>${number(s.known)}</b></span><span><i class="probable"></i>Prováveis <b>${number(s.probable)}</b></span><span><i class="unknown"></i>Desconhecidos <b>${number(s.unknown)}</b></span></div><p class="muted poi-note">${number(s.recurring_unknowns)} cluster(s) desconhecido(s) recorrente(s) no período.</p></article>
      </div>

      <article class="panel poi-chart-panel poi-heat-panel"><div class="poi-panel-title"><div><p class="eyebrow">MAPA DE CALOR</p><h3>Dia da semana × hora</h3></div><span>mais claro = maior fluxo</span></div>${heatmap(data.heatmap || {})}</article>

      <div class="poi-analytics-grid">
        <article class="panel poi-chart-panel"><div class="poi-panel-title"><div><p class="eyebrow">CÂMERAS</p><h3>Locais mais movimentados</h3></div></div>${bars(data.cameras)}</article>
        <article class="panel poi-chart-panel"><div class="poi-panel-title"><div><p class="eyebrow">PESSOAS</p><h3>Mais frequentes</h3></div></div>${bars(data.people)}</article>
        <article class="panel poi-chart-panel"><div class="poi-panel-title"><div><p class="eyebrow">PERMANÊNCIA</p><h3>Duração das passagens</h3></div></div>${bars(data.duration_buckets)}</article>
        <article class="panel poi-chart-panel"><div class="poi-panel-title"><div><p class="eyebrow">TRAJETOS</p><h3>Transições entre câmeras</h3></div></div><div class="poi-transition-list">${(data.transitions || []).length ? data.transitions.map(item => `<div><span>${escapeHtml(item.from)} <b>→</b> ${escapeHtml(item.to)}</span><strong>${number(item.count)}</strong></div>`).join('') : '<p class="muted">É preciso observar a mesma pessoa identificada em câmeras diferentes dentro de 30 minutos.</p>'}</div></article>
      </div>

      <article class="panel poi-routine-panel"><div class="poi-panel-title"><div><p class="eyebrow">ROTINA OBSERVADA</p><h3>Padrões já visíveis no histórico</h3></div><span>descritivo, não predição</span></div><div class="poi-routine-grid">${(data.routines || []).length ? data.routines.map(item => `<div class="poi-routine-card"><div><strong>${escapeHtml(item.name)}</strong><small>${number(item.count)} passagem(ns) · ${number(item.active_days)} dia(s)</small></div><span>${item.typical_hour_label ? `Mais comum: <b>${escapeHtml(item.typical_hour_label)}</b>` : 'Horário ainda disperso'}</span><span>Dias fortes: <b>${(item.strong_weekdays || []).map(escapeHtml).join(', ') || '—'}</b></span></div>`).join('') : '<p class="muted">Com três ou mais aparições identificadas, padrões individuais começam a aparecer aqui.</p>'}</div><p class="muted poi-note">Esses padrões resumem o histórico existente. Uma camada futura de previsão poderá usar estas distribuições sem alterar o motor de visão.</p></article>`;
  }

  async function loadAnalytics() {
    const root = document.getElementById('analyticsBody');
    if (!root) return;
    root.innerHTML = '<div class="panel"><p class="muted">Calculando histórico local…</p></div>';
    const days = Number(document.getElementById('analyticsDays')?.value || 30);
    let tz = 'UTC';
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (_) {}
    try {
      analyticsData = await api(`/api/analytics/overview?days=${encodeURIComponent(days)}&tz=${encodeURIComponent(tz)}`);
      renderAnalytics();
    } catch (error) {
      root.innerHTML = `<div class="panel"><p class="muted">Não foi possível carregar o Dashboard: ${escapeHtml(error.message)}</p></div>`;
    }
  }

  function start() {
    if (!installViews()) return false;
    installBottomNav();
    syncNavigation(state.view || 'dashboard');
    const requested = new URLSearchParams(location.search).get('view');
    if (requested === 'analytics' || requested === 'more') setTimeout(() => setView(requested), 80);
    return true;
  }

  if (!start()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (start() || attempts > 40) clearInterval(timer);
    }, 100);
  }
})();
