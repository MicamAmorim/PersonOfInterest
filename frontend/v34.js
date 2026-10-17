(() => {
  // V3/V4 extension loaded after the V2 runtime. Keep legacy camera/PTZ code and
  // replace only the parts that need identity, alerts or same-origin WebRTC.
  state.identityClusters = [];
  state.alertRules = [];

  const legacySetView = setView;

  function sameOriginCameraUrl(camera, speakerOn = false, micOn = false) {
    const params = new URLSearchParams({
      camera_id: String(camera.id),
      listen: speakerOn ? '1' : '0',
      microphone: micOn ? '1' : '0',
    });
    return `/camera-webrtc.html?${params.toString()}`;
  }

  // Always use the FastAPI -> go2rtc WebSocket proxy. This removes direct :1984
  // browser access and therefore works inside HTTPS Tailscale Serve and PWAs.
  viewerMediaUrl = function(camera, speakerOn, micOn) {
    return sameOriginCameraUrl(camera, speakerOn, micOn);
  };

  cameraCard = function(camera) {
    const [label, cls] = statusLabel(camera);
    const preview = camera.enabled && camera.sync_status === 'ok'
      ? `<iframe src="${sameOriginCameraUrl(camera)}" title="${escapeHtml(camera.name)}" loading="lazy" allow="autoplay"></iframe><span class="live-badge">LIVE</span>`
      : `<div class="camera-preview disabled"><span>${camera.sync_status === 'error' ? 'Stream indisponível' : 'Câmera desativada'}</span></div>`;
    return `<article class="camera-card" data-id="${camera.id}"><div class="camera-preview">${preview}</div><div class="camera-meta"><div><h3>${escapeHtml(camera.name)}</h3><p>${escapeHtml(camera.location || 'Sem local definido')}</p></div><span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span></div></article>`;
  };

  function installViews() {
    const nav = document.querySelector('.sidebar nav');
    const settingsNav = nav?.querySelector('[data-view="settings"]');
    if (nav && !nav.querySelector('[data-view="identity"]')) {
      const identityBtn = document.createElement('button');
      identityBtn.className = 'nav-item';
      identityBtn.dataset.view = 'identity';
      identityBtn.innerHTML = '<span>◎</span> Pessoas';
      const alertsBtn = document.createElement('button');
      alertsBtn.className = 'nav-item';
      alertsBtn.dataset.view = 'alerts';
      alertsBtn.innerHTML = '<span>♢</span> Alertas';
      nav.insertBefore(identityBtn, settingsNav || null);
      nav.insertBefore(alertsBtn, settingsNav || null);
      identityBtn.addEventListener('click', () => setView('identity'));
      alertsBtn.addEventListener('click', () => setView('alerts'));
    }

    const main = document.querySelector('main.main');
    const settings = $('#settingsView');
    if (main && settings && !$('#identityView')) {
      const identity = document.createElement('section');
      identity.id = 'identityView';
      identity.className = 'view';
      identity.innerHTML = `
        <div class="panel">
          <div class="panel-header identity-header">
            <div><p class="eyebrow">V3 · IDENTIDADE</p><h2>Quem é esta pessoa?</h2><p class="muted paragraph">Rostos desconhecidos são agrupados por embedding. Ao dar um nome, todo o histórico daquele grupo é associado retroativamente.</p></div>
            <div class="identity-actions"><button class="button ghost small" id="identityReindex">Reprocessar histórico</button><button class="button ghost small" id="identityRefresh">↻ Atualizar</button></div>
          </div>
          <div id="identityStatus" class="identity-status muted">Carregando identidade…</div>
          <div id="identityGrid" class="identity-grid"></div>
        </div>`;
      main.insertBefore(identity, settings);

      const alerts = document.createElement('section');
      alerts.id = 'alertsView';
      alerts.className = 'view';
      alerts.innerHTML = `
        <div class="stats-grid alert-stats">
          <article class="stat-card"><span>Eventos</span><strong id="statsTotal">0</strong><small>no período</small></article>
          <article class="stat-card"><span>Conhecidos</span><strong id="statsKnown">0</strong><small>identificados</small></article>
          <article class="stat-card"><span>Desconhecidos</span><strong id="statsUnknown">0</strong><small>sem identidade</small></article>
          <article class="stat-card"><span>Pessoas</span><strong id="statsPeople">0</strong><small>únicas conhecidas</small></article>
        </div>
        <div class="settings-grid v4-grid">
          <article class="panel info-panel">
            <p class="eyebrow">WEB PUSH · PWA</p><h2>Notificações</h2>
            <p id="pushStatusText" class="muted paragraph">Verificando suporte…</p>
            <div class="push-actions"><button class="button primary" id="enablePushBtn">Ativar notificações neste dispositivo</button><button class="button ghost" id="testPushBtn">Enviar teste</button></div>
            <p class="field-help">No iPhone/iPad, instale primeiro o PersonOfInterest na Tela de Início. Para acesso remoto use a URL HTTPS do Tailscale Serve.</p>
          </article>
          <article class="panel info-panel">
            <p class="eyebrow">REGRAS</p><h2>Novo alerta</h2>
            <div class="alert-form">
              <label>Nome<input id="ruleName" value="Desconhecido detectado" maxlength="120" /></label>
              <label>Câmera<select id="ruleCamera"><option value="">Todas as câmeras</option></select></label>
              <label>Quem<select id="ruleSubject"><option value="unknown">Desconhecidos</option><option value="any">Qualquer pessoa</option></select></label>
              <label>De<input id="ruleStart" type="time" /></label>
              <label>Até<input id="ruleEnd" type="time" /></label>
              <label>Cooldown (min)<input id="ruleCooldown" type="number" min="0" max="1440" value="5" /></label>
            </div>
            <div class="rule-buttons"><button class="button ghost" id="nightRuleBtn">Exemplo: 23h–6h</button><button class="button primary" id="saveRuleBtn">Criar regra</button></div>
          </article>
        </div>
        <div class="panel rules-panel"><div class="panel-header"><div><p class="eyebrow">AUTOMAÇÃO</p><h2>Regras ativas</h2></div><button class="button ghost small" id="rulesRefresh">↻ Atualizar</button></div><div id="rulesList" class="rules-list"></div></div>
        <div class="panel stats-panel"><div class="panel-header"><div><p class="eyebrow">ESTATÍSTICAS</p><h2>Distribuição</h2></div></div><div id="statsBreakdown" class="stats-breakdown"></div></div>`;
      main.insertBefore(alerts, settings);
    }

    $('#identityRefresh')?.addEventListener('click', loadIdentity);
    $('#identityReindex')?.addEventListener('click', reindexIdentity);
    $('#enablePushBtn')?.addEventListener('click', enablePush);
    $('#testPushBtn')?.addEventListener('click', testPush);
    $('#saveRuleBtn')?.addEventListener('click', createRule);
    $('#nightRuleBtn')?.addEventListener('click', () => { $('#ruleStart').value = '23:00'; $('#ruleEnd').value = '06:00'; });
    $('#rulesRefresh')?.addEventListener('click', loadAlerts);
  }

  setView = function(view) {
    if (!['identity', 'alerts'].includes(view)) {
      legacySetView(view);
      return;
    }
    state.view = view;
    $('#pageTitle').textContent = view === 'identity' ? 'Pessoas' : 'Alertas e inteligência';
    $$('.view').forEach(el => el.classList.remove('active'));
    $(`#${view}View`)?.classList.add('active');
    $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
    if (view === 'identity') loadIdentity();
    if (view === 'alerts') loadAlerts();
  };

  function formatWhen(raw) {
    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? raw : date.toLocaleString('pt-BR');
  }

  async function loadIdentity() {
    const grid = $('#identityGrid');
    if (!grid) return;
    try {
      const [status, clusters] = await Promise.all([api('/api/identity/status'), api('/api/identity/clusters'), loadPersons()]);
      state.identityClusters = clusters || [];
      const counts = status.states || {};
      $('#identityStatus').textContent = `Motor: ${status.status} · amostras ${status.face_samples || 0} · grupos desconhecidos ${status.open_clusters || 0} · pendentes ${counts.pending || 0}` + (status.error ? ` · ${status.error}` : '');
      if (!state.identityClusters.length) {
        grid.innerHTML = '<div class="empty-state compact"><div class="empty-icon">◎</div><h3>Nenhum rosto desconhecido aguardando identificação</h3><p>Novos rostos serão agrupados automaticamente.</p></div>';
        return;
      }
      grid.innerHTML = state.identityClusters.map(cluster => `
        <article class="identity-card" data-cluster="${cluster.id}">
          <div class="identity-face">${cluster.face_url ? `<img src="${cluster.face_url}" loading="lazy" alt="Rosto desconhecido">` : '<span>Sem crop</span>'}</div>
          <div class="identity-body"><div><strong>Desconhecido #${cluster.id}</strong><span>${cluster.sample_count} aparição(ões) · ${escapeHtml(cluster.cameras || 'câmera')}</span><span>${formatWhen(cluster.first_seen)} → ${formatWhen(cluster.last_seen)}</span></div>
          <label>Associar a<select data-person-for="${cluster.id}"><option value="">Novo nome…</option>${state.persons.map(person => `<option value="${person.id}">${escapeHtml(person.name)}</option>`).join('')}</select></label>
          <input data-name-for="${cluster.id}" placeholder="Nome da pessoa" maxlength="120" />
          <button class="button primary small" data-assign-cluster="${cluster.id}">Identificar e aplicar ao histórico</button></div>
        </article>`).join('');
      $$('[data-assign-cluster]').forEach(button => button.addEventListener('click', () => assignCluster(Number(button.dataset.assignCluster))));
      $$('[data-person-for]').forEach(select => select.addEventListener('change', () => {
        const input = $(`[data-name-for="${select.dataset.personFor}"]`);
        input.disabled = Boolean(select.value);
        if (select.value) input.value = '';
      }));
    } catch (error) {
      grid.innerHTML = `<p class="muted">Falha ao carregar identidade: ${escapeHtml(error.message)}</p>`;
    }
  }

  async function assignCluster(clusterId) {
    const select = $(`[data-person-for="${clusterId}"]`);
    const input = $(`[data-name-for="${clusterId}"]`);
    const payload = select?.value ? { person_id: Number(select.value) } : { name: input?.value.trim() };
    if (!payload.person_id && !payload.name) { toast('Escolha uma pessoa ou informe um nome.', 'error'); return; }
    try {
      const result = await api(`/api/identity/clusters/${clusterId}/assign`, { method: 'POST', body: JSON.stringify(payload) });
      toast(`${result.person_name}: histórico associado.`);
      await Promise.all([loadIdentity(), loadEvents(), loadPersons()]);
    } catch (error) { toast(error.message, 'error'); }
  }

  async function identifyEvent(eventId) {
    const event = state.events.find(item => item.id === eventId);
    if (!event) return;
    const name = prompt('Quem é esta pessoa? Digite o nome. O grupo inteiro será associado retroativamente quando houver cluster.', event.person_name || '');
    if (!name?.trim()) return;
    try {
      const result = await api(`/api/identity/events/${eventId}/assign`, { method: 'POST', body: JSON.stringify({ name: name.trim() }) });
      toast(`${result.person_name} associado ao histórico.`);
      await Promise.all([loadEvents(), loadPersons(), loadIdentity()]);
    } catch (error) { toast(error.message, 'error'); }
  }

  async function reindexIdentity() {
    if (!confirm('Reprocessar snapshots sem embedding facial? O processamento ocorrerá em segundo plano.')) return;
    try {
      const result = await api('/api/identity/reindex', { method: 'POST', body: '{}' });
      toast(`${result.queued} evento(s) enviados para análise.`);
      setTimeout(loadIdentity, 1200);
    } catch (error) { toast(error.message, 'error'); }
  }

  // Enhance the V2 timeline with identity state and a direct identification action.
  renderTimeline = function() {
    if (!$('#timelineGrid')) return;
    if (!state.events.length) {
      $('#timelineGrid').innerHTML = '<div class="empty-state compact"><div class="empty-icon">◷</div><h3>Nenhum evento encontrado</h3><p>Ajuste os filtros ou aguarde novas detecções.</p></div>';
      updateTimelineSelectionControls();
      return;
    }
    $('#timelineGrid').innerHTML = state.events.map(event => {
      const checked = state.selectedEventIds.has(event.id) ? 'checked' : '';
      let personLabel = event.person_name ? escapeHtml(event.person_name) : `Pessoa #${event.track_id ?? '—'}`;
      if (!event.person_name && event.identity_state === 'unknown' && event.unknown_cluster_id) personLabel = `Desconhecido #${event.unknown_cluster_id}`;
      if (!event.person_name && event.identity_state === 'pending') personLabel = 'Identificando…';
      const identityClass = event.person_name ? 'identified' : (event.identity_state === 'unknown' ? 'unknown' : '');
      return `<article class="event-card ${checked ? 'selected' : ''}" data-event-card="${event.id}">
        <div class="event-image">${event.snapshot_url ? `<img src="${event.snapshot_url}" loading="lazy" alt="Evento da câmera ${escapeHtml(event.camera_name)}">` : '<div class="event-placeholder">Sem imagem</div>'}
          <label class="event-select" title="Selecionar evento"><input type="checkbox" data-select-event="${event.id}" ${checked} /><span>✓</span></label>
          <button class="event-delete" data-delete-event="${event.id}" title="Excluir este evento">×</button>
        </div>
        <div class="event-meta"><div><strong>${escapeHtml(event.camera_name)}</strong><span>${escapeHtml(event.camera_location || 'Sem local')}</span></div><span class="status-pill ${identityClass}">${personLabel}</span></div>
        <div class="event-foot"><span>${formatWhen(event.created_at)}</span><span>${event.has_face ? `Face detectada${event.face_count > 1 ? ` (${event.face_count})` : ''}` : 'Sem face útil'}</span></div>
        <div class="event-actions">${event.person_name ? '' : `<button class="button ghost small" data-identify-event="${event.id}">Quem é?</button>`}</div>
      </article>`;
    }).join('');
    $$('[data-delete-event]').forEach(el => el.addEventListener('click', e => { e.stopPropagation(); deleteTimelineEvent(Number(el.dataset.deleteEvent)); }));
    $$('[data-select-event]').forEach(el => el.addEventListener('change', () => {
      const id = Number(el.dataset.selectEvent);
      if (el.checked) state.selectedEventIds.add(id); else state.selectedEventIds.delete(id);
      renderTimeline();
    }));
    $$('[data-identify-event]').forEach(el => el.addEventListener('click', () => identifyEvent(Number(el.dataset.identifyEvent))));
    updateTimelineSelectionControls();
  };

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    return Uint8Array.from([...raw].map(char => char.charCodeAt(0)));
  }

  async function enablePush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      toast('Este navegador não oferece Web Push.', 'error'); return;
    }
    if (!window.isSecureContext) { toast('Web Push exige HTTPS ou localhost. Use Tailscale Serve no celular.', 'error'); return; }
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { toast('Permissão de notificações não concedida.', 'error'); return; }
      const registration = await navigator.serviceWorker.ready;
      const { public_key } = await api('/api/push/vapid-public-key');
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(public_key) });
      const raw = subscription.toJSON();
      await api('/api/push/subscriptions', { method: 'POST', body: JSON.stringify({
        endpoint: raw.endpoint,
        p256dh: raw.keys.p256dh,
        auth: raw.keys.auth,
        expiration_time: raw.expirationTime,
        user_agent: navigator.userAgent,
      }) });
      toast('Notificações ativadas neste dispositivo.');
      await loadPushStatus();
    } catch (error) { toast(`Web Push: ${error.message}`, 'error'); }
  }

  async function loadPushStatus() {
    const text = $('#pushStatusText');
    if (!text) return;
    try {
      const result = await api('/api/push/status');
      const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
      text.textContent = `Servidor: ${result.status} · ${result.subscriptions} dispositivo(s) inscrito(s) · ${result.enabled_rules} regra(s) ativa(s)` + (!standalone && /iPhone|iPad|iPod/.test(navigator.userAgent) ? ' · no iOS, adicione à Tela de Início antes de ativar Push' : '');
    } catch (error) { text.textContent = `Push: ${error.message}`; }
  }

  async function testPush() {
    try {
      const result = await api('/api/push/test', { method: 'POST', body: '{}' });
      toast(`Push de teste: ${result.sent} enviado(s), ${result.failed} falha(s).`);
    } catch (error) { toast(error.message, 'error'); }
  }

  function populateRuleSelectors() {
    const camera = $('#ruleCamera');
    if (camera) camera.innerHTML = '<option value="">Todas as câmeras</option>' + state.cameras.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    const subject = $('#ruleSubject');
    if (subject) subject.innerHTML = '<option value="unknown">Desconhecidos</option><option value="any">Qualquer pessoa</option>' + state.persons.map(p => `<option value="person:${p.id}">${escapeHtml(p.name)}</option>`).join('');
  }

  async function createRule() {
    const subject = $('#ruleSubject').value;
    const payload = {
      name: $('#ruleName').value.trim() || 'Alerta PersonOfInterest',
      camera_id: $('#ruleCamera').value ? Number($('#ruleCamera').value) : null,
      person_id: subject.startsWith('person:') ? Number(subject.split(':')[1]) : null,
      unknown_only: subject === 'unknown',
      start_time: $('#ruleStart').value || null,
      end_time: $('#ruleEnd').value || null,
      weekdays: [0,1,2,3,4,5,6],
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
      cooldown_seconds: Math.max(0, Number($('#ruleCooldown').value || 5)) * 60,
      enabled: true,
    };
    try {
      await api('/api/alert-rules', { method: 'POST', body: JSON.stringify(payload) });
      toast('Regra criada.');
      await loadAlerts();
    } catch (error) { toast(error.message, 'error'); }
  }

  async function toggleRule(id, enabled) {
    try { await api(`/api/alert-rules/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }); await loadAlerts(); }
    catch (error) { toast(error.message, 'error'); }
  }

  async function deleteRule(id) {
    if (!confirm('Excluir esta regra de alerta?')) return;
    try { await api(`/api/alert-rules/${id}`, { method: 'DELETE' }); await loadAlerts(); }
    catch (error) { toast(error.message, 'error'); }
  }

  function renderRules() {
    const list = $('#rulesList');
    if (!list) return;
    if (!state.alertRules.length) { list.innerHTML = '<p class="muted">Nenhuma regra criada.</p>'; return; }
    list.innerHTML = state.alertRules.map(rule => {
      const target = rule.unknown_only ? 'Desconhecidos' : (rule.person_name || 'Qualquer pessoa');
      const camera = rule.camera_name || 'Todas as câmeras';
      const time = rule.start_time && rule.end_time ? `${rule.start_time}–${rule.end_time}` : '24 horas';
      return `<article class="rule-row"><div><strong>${escapeHtml(rule.name)}</strong><span>${escapeHtml(target)} · ${escapeHtml(camera)} · ${time} · cooldown ${Math.round(rule.cooldown_seconds/60)} min</span></div><div><label class="mini-switch"><input type="checkbox" data-toggle-rule="${rule.id}" ${rule.enabled ? 'checked' : ''}><span>${rule.enabled ? 'Ativa' : 'Pausada'}</span></label><button class="button danger small" data-delete-rule="${rule.id}">Excluir</button></div></article>`;
    }).join('');
    $$('[data-toggle-rule]').forEach(el => el.addEventListener('change', () => toggleRule(Number(el.dataset.toggleRule), el.checked)));
    $$('[data-delete-rule]').forEach(el => el.addEventListener('click', () => deleteRule(Number(el.dataset.deleteRule))));
  }

  async function loadStats() {
    try {
      const stats = await api('/api/stats/summary');
      $('#statsTotal').textContent = stats.total;
      $('#statsKnown').textContent = stats.known;
      $('#statsUnknown').textContent = stats.unknown;
      $('#statsPeople').textContent = stats.unique_known;
      const max = Math.max(1, ...stats.by_camera.map(item => item.count), ...stats.by_person.map(item => item.count));
      $('#statsBreakdown').innerHTML = `
        <div><h3>Por câmera</h3>${stats.by_camera.map(item => `<div class="stat-bar"><span>${escapeHtml(item.name)}</span><i style="width:${item.count/max*100}%"></i><b>${item.count}</b></div>`).join('') || '<p class="muted">Sem dados</p>'}</div>
        <div><h3>Por pessoa</h3>${stats.by_person.map(item => `<div class="stat-bar"><span>${escapeHtml(item.name)}</span><i style="width:${item.count/max*100}%"></i><b>${item.count}</b></div>`).join('') || '<p class="muted">Sem identidades ainda</p>'}</div>`;
    } catch (_) {}
  }

  async function loadAlerts() {
    try {
      await Promise.all([loadPersons(), loadPushStatus(), loadStats()]);
      state.alertRules = await api('/api/alert-rules');
      populateRuleSelectors();
      renderRules();
    } catch (error) { toast(`Alertas: ${error.message}`, 'error'); }
  }

  installViews();
  document.querySelector('.topbar .eyebrow').textContent = 'NVR LOCAL · V4';
  const architecture = $('#settingsView .info-panel strong');
  if (architecture) document.title = 'PersonOfInterest';

  // Re-render cards using same-origin WebRTC and restore deep links from Push.
  try { render(); } catch (_) {}
  const params = new URLSearchParams(location.search);
  const requestedView = params.get('view');
  if (['timeline', 'identity', 'alerts'].includes(requestedView)) setTimeout(() => setView(requestedView), 50);
})();
