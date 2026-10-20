(() => {
  const V58 = {
    storage: null,
    recording: [],
    recorderStatus: null,
    prototypes: [],
    recordings: [],
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function bytes(value) {
    let n = Number(value) || 0;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
  }

  function when(raw) {
    if (!raw) return '—';
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? String(raw) : d.toLocaleString('pt-BR');
  }

  function value(id, fallback = 0) {
    const el = document.getElementById(id);
    const number = Number(el?.value);
    return Number.isFinite(number) ? number : fallback;
  }

  function selected(id, fallback = '') {
    return document.getElementById(id)?.value || fallback;
  }

  function timeOptions(current, allowed = ['minutes', 'hours', 'days', 'weeks', 'months']) {
    const labels = { seconds: 'segundos', minutes: 'minutos', hours: 'horas', days: 'dias', weeks: 'semanas', months: 'meses' };
    return allowed.map(unit => `<option value="${unit}" ${unit === current ? 'selected' : ''}>${labels[unit]}</option>`).join('');
  }

  function installTimelineFilter() {
    if (document.getElementById('timelineFalsePositiveMode')) return;
    const panel = document.querySelector('.timeline-filter-panel');
    const buttons = panel?.querySelector('.timeline-filter-buttons');
    if (!panel || !buttons) return;

    const label = document.createElement('label');
    label.innerHTML = `Exibição<select id="timelineFalsePositiveMode">
      <option value="normal">Eventos normais</option>
      <option value="false">Falsos positivos</option>
      <option value="all">Todos</option>
    </select>`;
    panel.insertBefore(label, buttons);

    async function loadEventsV58() {
      try {
        const params = typeof timelineParams === 'function' ? timelineParams() : new URLSearchParams();
        params.set('false_positive_mode', document.getElementById('timelineFalsePositiveMode')?.value || 'normal');
        params.set('limit', '500');
        state.events = await api(`/api/storage/events?${params.toString()}`);
        const visible = new Set(state.events.map(event => event.id));
        state.selectedEventIds = new Set([...state.selectedEventIds].filter(id => visible.has(id)));
        if (document.getElementById('eventCount')) document.getElementById('eventCount').textContent = state.events.length;
        renderTimeline();
      } catch (error) {
        const grid = document.getElementById('timelineGrid');
        if (grid) grid.innerHTML = `<p class="muted">Falha ao carregar timeline: ${q(error.message)}</p>`;
      }
    }

    try { loadEvents = loadEventsV58; } catch (_) {}

    const intercept = (id, eventName = 'change') => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener(eventName, event => {
        event.stopImmediatePropagation();
        loadEventsV58();
      }, true);
    };
    intercept('timelineRefresh', 'click');
    intercept('timelineCamera');
    intercept('timelinePerson');
    intercept('timelineFace');
    intercept('timelineFalsePositiveMode');

    const clear = document.getElementById('timelineClearFilters');
    clear?.addEventListener('click', event => {
      event.stopImmediatePropagation();
      ['timelineCamera', 'timelinePerson', 'timelineDateFrom', 'timelineDateTo', 'timelineTimeFrom', 'timelineTimeTo', 'timelineFace'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      const fp = document.getElementById('timelineFalsePositiveMode');
      if (fp) fp.value = 'normal';
      loadEventsV58();
    }, true);

    loadEventsV58();
  }

  function installSettingsPanel() {
    const view = document.getElementById('settingsView');
    if (!view || document.getElementById('v58StorageRoot')) return Boolean(document.getElementById('v58StorageRoot'));
    const root = document.createElement('div');
    root.id = 'v58StorageRoot';
    root.className = 'v58-root';
    root.innerHTML = `
      <section class="panel v58-panel">
        <div class="panel-header v58-heading">
          <div><p class="eyebrow">ARMAZENAMENTO · RETENÇÃO</p><h2>Gerenciamento da base</h2><p class="muted paragraph">Limite Timeline, referências automáticas e gravações sem alterar o motor de visão. Limpeza da Timeline fica desligada até você ativar.</p></div>
          <div class="v58-actions"><button class="button ghost small" id="v58Refresh">↻ Atualizar</button><button class="button danger small" id="v58CleanupNow">Executar limpeza agora</button></div>
        </div>
        <div id="v58StorageStats" class="v58-stats"><p class="muted">Carregando uso de disco…</p></div>
        <div id="v58StorageForm" class="v58-form"><p class="muted">Carregando configurações…</p></div>
      </section>

      <section class="panel v58-panel">
        <div class="panel-header v58-heading"><div><p class="eyebrow">NVR · VÍDEO</p><h2>Gravação por câmera</h2><p class="muted paragraph">FFmpeg lê o restream local do go2rtc; tracker, Face ReID e Body ReID não participam da gravação.</p></div><span id="v58RecorderBadge" class="status-pill">verificando FFmpeg…</span></div>
        <div id="v58RecordingGrid" class="v58-recording-grid"><p class="muted">Carregando câmeras…</p></div>
        <div class="v58-subsection"><div class="v58-subhead"><div><strong>Gravações recentes</strong><span>Arquivos segmentados em disco</span></div><button class="button ghost small" id="v58RecordingsRefresh">↻ Atualizar</button></div><div id="v58RecordingsList" class="v58-recording-list"><p class="muted">Carregando…</p></div></div>
      </section>

      <section class="panel v58-panel">
        <div class="panel-header v58-heading"><div><p class="eyebrow">HARD NEGATIVE · MEMÓRIA PERSISTENTE</p><h2>Falsos positivos aprendidos</h2><p class="muted paragraph">Protótipos por câmera sobrevivem à limpeza da Timeline. Novos matches fortes são suprimidos antes do Push e aparecem apenas no filtro “Falsos positivos”.</p></div><button class="button ghost small" id="v58BackfillFP">Consolidar falsos positivos atuais</button></div>
        <div id="v58PrototypeGrid" class="v58-prototype-grid"><p class="muted">Carregando memória negativa…</p></div>
      </section>`;
    view.appendChild(root);

    document.getElementById('v58Refresh')?.addEventListener('click', loadAll);
    document.getElementById('v58CleanupNow')?.addEventListener('click', runCleanup);
    document.getElementById('v58RecordingsRefresh')?.addEventListener('click', loadRecordings);
    document.getElementById('v58BackfillFP')?.addEventListener('click', backfillFalsePositives);
    return true;
  }

  function renderStorage(status) {
    V58.storage = status.settings || {};
    const b = status.bytes || {};
    const c = status.counts || {};
    const stats = document.getElementById('v58StorageStats');
    if (stats) stats.innerHTML = `
      <article><span>Timeline</span><strong>${bytes(b.timeline)}</strong><small>${c.events || 0} eventos</small></article>
      <article><span>Gravações</span><strong>${bytes(b.recordings)}</strong><small>vídeos salvos</small></article>
      <article><span>Referências</span><strong>${(c.face_samples || 0) + (c.body_samples || 0)}</strong><small>${c.face_samples || 0} face · ${c.body_samples || 0} body</small></article>
      <article><span>Disco livre</span><strong>${bytes(b.disk_free)}</strong><small>de ${bytes(b.disk_total)}</small></article>`;

    const s = V58.storage;
    const form = document.getElementById('v58StorageForm');
    if (!form) return;
    form.innerHTML = `
      <div class="v58-section-title"><strong>Timeline e embeddings</strong><span>A limpeza só roda quando “Ativar retenção automática” estiver marcado.</span></div>
      <label class="switch-row v58-wide"><span><strong>Ativar retenção automática da Timeline</strong><small>Remove eventos antigos e reduz galerias automáticas conforme os limites abaixo.</small></span><input id="v58CleanupEnabled" type="checkbox" ${s.cleanup_enabled ? 'checked' : ''}></label>
      <label>Manter Timeline por<div class="v58-inline"><input id="v58TimelineRetentionValue" type="number" min="0.01" step="0.01" value="${Number(s.timeline_retention_value ?? 30)}"><select id="v58TimelineRetentionUnit">${timeOptions(s.timeline_retention_unit || 'days')}</select></div></label>
      <label>Máximo da Timeline (GB)<input id="v58TimelineMaxGb" type="number" min="0.1" step="0.1" value="${Number(s.timeline_max_gb ?? 10)}"></label>
      <label>Faces automáticas / pessoa<input id="v58FaceLimit" type="number" min="1" max="10000" value="${Number(s.face_auto_limit_per_person ?? 30)}"></label>
      <label>Bodies automáticos / pessoa<input id="v58BodyLimit" type="number" min="1" max="10000" value="${Number(s.body_auto_limit_per_person ?? 50)}"></label>
      <label>Executar limpeza a cada (min)<input id="v58CleanupInterval" type="number" min="1" step="1" value="${Number(s.cleanup_interval_minutes ?? 15)}"></label>
      <label class="switch-row v58-wide"><span><strong>Proteger referências manuais</strong><small>Eventos/referências confirmados manualmente ficam fora da poda automática.</small></span><input id="v58ProtectManual" type="checkbox" ${s.protect_manual ? 'checked' : ''}></label>

      <div class="v58-section-title"><strong>Falsos positivos</strong><span>Limites independentes da Timeline.</span></div>
      <label>Protótipos máximos / câmera<input id="v58FpPrototypeLimit" type="number" min="1" max="10000" value="${Number(s.false_positive_max_prototypes_per_camera ?? 100)}"></label>
      <label>Exemplos / protótipo<input id="v58FpExampleLimit" type="number" min="1" max="1000" value="${Number(s.false_positive_examples_per_prototype ?? 5)}"></label>

      <div class="v58-section-title"><strong>Retenção de gravações</strong><span>Aplicada mesmo com a limpeza da Timeline desligada, para proteger o disco do NVR.</span></div>
      <label>Manter vídeos por<div class="v58-inline"><input id="v58RecordingRetentionValue" type="number" min="0.01" step="0.01" value="${Number(s.recording_retention_value ?? 30)}"><select id="v58RecordingRetentionUnit">${timeOptions(s.recording_retention_unit || 'days')}</select></div></label>
      <label>Máximo para vídeos (GB)<input id="v58RecordingMaxGb" type="number" min="0.1" step="0.1" value="${Number(s.recording_max_gb ?? 500)}"></label>
      <label>Reserva mínima livre no disco (GB)<input id="v58DiskReserveGb" type="number" min="0" step="0.1" value="${Number(s.disk_reserve_gb ?? 10)}"></label>
      <div class="v58-wide v58-save-row"><button class="button primary" id="v58SaveStorage">Salvar política de armazenamento</button><span class="muted">Última limpeza: ${q(status.last_cleanup ? when(status.last_cleanup) : 'ainda não executada')}</span></div>`;
    document.getElementById('v58SaveStorage')?.addEventListener('click', saveStorage);
  }

  async function saveStorage() {
    const enabling = document.getElementById('v58CleanupEnabled')?.checked;
    if (enabling && !V58.storage?.cleanup_enabled) {
      const ok = confirm('Ativar retenção automática permite excluir eventos, snapshots e referências automáticas que ultrapassarem os limites definidos. Referências manuais protegidas serão preservadas. Continuar?');
      if (!ok) { document.getElementById('v58CleanupEnabled').checked = false; return; }
    }
    const payload = {
      cleanup_enabled: Boolean(enabling),
      timeline_retention_value: value('v58TimelineRetentionValue', 30),
      timeline_retention_unit: selected('v58TimelineRetentionUnit', 'days'),
      timeline_max_gb: value('v58TimelineMaxGb', 10),
      face_auto_limit_per_person: value('v58FaceLimit', 30),
      body_auto_limit_per_person: value('v58BodyLimit', 50),
      cleanup_interval_minutes: value('v58CleanupInterval', 15),
      protect_manual: Boolean(document.getElementById('v58ProtectManual')?.checked),
      false_positive_max_prototypes_per_camera: value('v58FpPrototypeLimit', 100),
      false_positive_examples_per_prototype: value('v58FpExampleLimit', 5),
      recording_retention_value: value('v58RecordingRetentionValue', 30),
      recording_retention_unit: selected('v58RecordingRetentionUnit', 'days'),
      recording_max_gb: value('v58RecordingMaxGb', 500),
      disk_reserve_gb: value('v58DiskReserveGb', 10),
    };
    try {
      await api('/api/storage/settings', { method: 'PUT', body: JSON.stringify(payload) });
      toast('Política de armazenamento salva.');
      await loadStorage();
    } catch (error) { toast(`Armazenamento: ${error.message}`, 'error'); }
  }

  async function runCleanup() {
    if (!confirm('Executar agora as políticas de retenção configuradas? Arquivos removidos por retenção não podem ser recuperados.')) return;
    try {
      const result = await api('/api/storage/cleanup', { method: 'POST', body: '{}' });
      toast(`Limpeza concluída: ${(result.timeline_removed_by_age || 0) + (result.timeline_removed_by_size || 0)} evento(s), ${result.recording_files_removed || 0} vídeo(s).`);
      await Promise.all([loadStorage(), typeof loadEvents === 'function' ? loadEvents() : Promise.resolve()]);
    } catch (error) { toast(`Limpeza: ${error.message}`, 'error'); }
  }

  function renderRecording(settings, status) {
    V58.recording = settings || [];
    V58.recorderStatus = status || {};
    const badge = document.getElementById('v58RecorderBadge');
    if (badge) {
      badge.textContent = status.ffmpeg_available ? `FFmpeg pronto · ${status.sessions?.length || 0} ativo(s)` : 'FFmpeg indisponível';
      badge.className = `status-pill ${status.ffmpeg_available ? '' : 'error'}`;
    }
    const grid = document.getElementById('v58RecordingGrid');
    if (!grid) return;
    if (!settings.length) {
      grid.innerHTML = '<p class="muted">Nenhuma câmera cadastrada.</p>';
      return;
    }
    const sessions = new Map((status.sessions || []).map(item => [Number(item.camera_id), item]));
    grid.innerHTML = settings.map(item => {
      const id = Number(item.camera_id);
      const session = sessions.get(id);
      const error = status.errors?.[String(id)];
      return `<article class="v58-camera-recording" data-record-camera="${id}">
        <div class="v58-camera-recording-head"><div><strong>${q(item.camera_name)}</strong><span>${session?.running ? `● gravando ${q(session.mode)}` : item.mode === 'off' ? 'gravação desativada' : 'aguardando'}</span></div>${error ? `<span class="v58-error">${q(error)}</span>` : ''}</div>
        <label>Modo<select data-rec-mode="${id}"><option value="off" ${item.mode === 'off' ? 'selected' : ''}>Desativada</option><option value="event" ${item.mode === 'event' ? 'selected' : ''}>Somente quando houver evento</option><option value="continuous" ${item.mode === 'continuous' ? 'selected' : ''}>Contínua 24/7</option></select></label>
        <label>Tempo após evento<div class="v58-inline"><input data-rec-event-value="${id}" type="number" min="1" step="1" value="${Number(item.event_duration_value || 60)}"><select data-rec-event-unit="${id}">${timeOptions(item.event_duration_unit || 'seconds', ['seconds','minutes','hours','days'])}</select></div></label>
        <label>Duração dos arquivos<div class="v58-inline"><input data-rec-segment-value="${id}" type="number" min="1" step="1" value="${Number(item.segment_duration_value || 5)}"><select data-rec-segment-unit="${id}">${timeOptions(item.segment_duration_unit || 'minutes', ['minutes','hours','days'])}</select></div></label>
        <button class="button primary small" data-rec-save="${id}">Salvar gravação desta câmera</button>
      </article>`;
    }).join('');
    grid.querySelectorAll('[data-rec-save]').forEach(button => button.addEventListener('click', () => saveRecordingCamera(Number(button.dataset.recSave))));
  }

  async function saveRecordingCamera(cameraId) {
    const mode = document.querySelector(`[data-rec-mode="${cameraId}"]`)?.value || 'off';
    const old = V58.recording.find(item => Number(item.camera_id) === cameraId)?.mode || 'off';
    if (mode !== 'off' && old === 'off') {
      const text = mode === 'continuous'
        ? 'Ativar gravação contínua nesta câmera? O limite de disco e a retenção configurados em Armazenamento serão aplicados.'
        : 'Ativar gravação por evento nesta câmera? Cada evento iniciará/estenderá uma gravação pelo tempo configurado.';
      if (!confirm(text)) return;
    }
    const payload = {
      mode,
      event_duration_value: Number(document.querySelector(`[data-rec-event-value="${cameraId}"]`)?.value || 60),
      event_duration_unit: document.querySelector(`[data-rec-event-unit="${cameraId}"]`)?.value || 'seconds',
      segment_duration_value: Number(document.querySelector(`[data-rec-segment-value="${cameraId}"]`)?.value || 5),
      segment_duration_unit: document.querySelector(`[data-rec-segment-unit="${cameraId}"]`)?.value || 'minutes',
    };
    try {
      await api(`/api/recording/cameras/${cameraId}`, { method: 'PUT', body: JSON.stringify(payload) });
      toast('Configuração de gravação salva.');
      setTimeout(loadRecording, 500);
    } catch (error) { toast(`Gravação: ${error.message}`, 'error'); }
  }

  function renderRecordings(items) {
    V58.recordings = items || [];
    const list = document.getElementById('v58RecordingsList');
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<p class="muted">Nenhuma gravação indexada ainda.</p>';
      return;
    }
    list.innerHTML = items.slice(0, 30).map(item => `
      <article><div><strong>${q(item.camera_name)}</strong><span>${item.mode === 'event' ? 'evento' : 'contínua'} · ${when(item.started_at || item.created_at)} · ${bytes(item.size_bytes)}</span></div><a class="button ghost tiny" href="${q(item.file_url)}" target="_blank" rel="noopener">Abrir vídeo</a></article>`).join('');
  }

  function renderPrototypes(items) {
    V58.prototypes = items || [];
    const grid = document.getElementById('v58PrototypeGrid');
    if (!grid) return;
    if (!items.length) {
      grid.innerHTML = '<div class="empty-state compact"><div class="empty-icon">◇</div><h3>Nenhum falso positivo aprendido</h3><p>Ao marcar manualmente um objeto como falso positivo, ele passará a aparecer aqui.</p></div>';
      return;
    }
    grid.innerHTML = items.map(item => `
      <article class="v58-prototype ${item.active ? '' : 'disabled'}">
        <div class="v58-prototype-image">${item.image_url ? `<img src="${q(item.image_url)}" loading="lazy" alt="Falso positivo aprendido">` : '<span>sem imagem</span>'}</div>
        <div class="v58-prototype-meta"><strong>${q(item.camera_name)} · protótipo #${item.id}</strong><span>${item.support_count || 0} exemplo(s) manual(is) · qualidade ${Math.round((Number(item.quality) || 0) * 100)}%</span><span>${when(item.first_seen)} → ${when(item.last_seen)}</span><b>${item.active ? 'ATIVO · suprime matches fortes' : 'DESATIVADO · ignorado pelo matcher'}</b></div>
        <button class="button ${item.active ? 'ghost' : 'primary'} small" data-fp-state="${item.id}|${item.active ? '0' : '1'}">${item.active ? 'Desaprender' : 'Reativar'}</button>
      </article>`).join('');
    grid.querySelectorAll('[data-fp-state]').forEach(button => button.addEventListener('click', async () => {
      const [id, active] = button.dataset.fpState.split('|');
      const next = active === '1';
      if (!next && !confirm('Desativar este protótipo? Futuras detecções deixarão de ser suprimidas por esta memória negativa.')) return;
      try {
        await api(`/api/false-positives/prototypes/${id}/state`, { method: 'PUT', body: JSON.stringify({ active: next }) });
        toast(next ? 'Memória negativa reativada.' : 'Memória negativa desativada.');
        await loadPrototypes();
      } catch (error) { toast(error.message, 'error'); }
    }));
  }

  async function backfillFalsePositives() {
    if (!confirm('Consolidar falsos positivos manuais já existentes em protótipos persistentes e reaplicar somente correspondências retroativas muito fortes?')) return;
    try {
      const result = await api('/api/false-positives/backfill', { method: 'POST', body: '{}' });
      toast(`${result.learned || 0} exemplo(s) consolidado(s) · ${result.propagated || 0} ocorrência(s) retroativa(s) suprimida(s).`);
      await Promise.all([loadPrototypes(), typeof loadEvents === 'function' ? loadEvents() : Promise.resolve()]);
    } catch (error) { toast(`Falsos positivos: ${error.message}`, 'error'); }
  }

  async function loadStorage() {
    try { renderStorage(await api('/api/storage/status')); }
    catch (error) {
      const form = document.getElementById('v58StorageForm');
      if (form) form.innerHTML = `<p class="muted">${q(error.message)}</p>`;
    }
  }

  async function loadRecording() {
    try {
      const [settings, status] = await Promise.all([api('/api/recording/settings'), api('/api/recording/status')]);
      renderRecording(settings, status);
    } catch (error) {
      const grid = document.getElementById('v58RecordingGrid');
      if (grid) grid.innerHTML = `<p class="muted">${q(error.message)}</p>`;
    }
  }

  async function loadRecordings() {
    try { renderRecordings(await api('/api/recordings?limit=30')); }
    catch (error) {
      const list = document.getElementById('v58RecordingsList');
      if (list) list.innerHTML = `<p class="muted">${q(error.message)}</p>`;
    }
  }

  async function loadPrototypes() {
    try { renderPrototypes(await api('/api/false-positives/prototypes')); }
    catch (error) {
      const grid = document.getElementById('v58PrototypeGrid');
      if (grid) grid.innerHTML = `<p class="muted">${q(error.message)}</p>`;
    }
  }

  async function loadAll() {
    await Promise.all([loadStorage(), loadRecording(), loadRecordings(), loadPrototypes()]);
  }

  installTimelineFilter();
  if (installSettingsPanel()) loadAll();
  else {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      installTimelineFilter();
      if (installSettingsPanel()) {
        clearInterval(timer);
        loadAll();
      } else if (attempts > 40) clearInterval(timer);
    }, 150);
  }
})();
