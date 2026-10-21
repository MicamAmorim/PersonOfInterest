(() => {
  const V60 = {
    cameras: [], data: null, cameraId: null, date: '', currentSecond: 0,
    currentRecording: null, selectedEventId: null, showFalsePositives: false,
    followLive: false, zoom: window.matchMedia('(max-width: 760px)').matches ? 4 : 1,
    refreshTimer: null, loadToken: 0,
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const el = id => document.getElementById(id);

  function localDateString(date = new Date()) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  function clock(seconds, withSeconds = true) {
    const total = Math.max(0, Math.min(86400, Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}${withSeconds ? `:${String(s).padStart(2, '0')}` : ''}`;
  }

  function modeLabel(mode) {
    if (mode === 'continuous') return 'Gravação contínua';
    if (mode === 'event') return 'Somente eventos';
    return 'Sem gravação';
  }

  function isFalsePositiveEvent(item) {
    const state = String(item?.identity_state || '').trim().toLowerCase();
    const label = String(item?.label || '').trim().toLowerCase();
    return state === 'false_positive' || label === 'falso positivo';
  }

  function falsePositiveIds() {
    return new Set((V60.data?.events || []).filter(isFalsePositiveEvent).map(item => Number(item.id)));
  }

  function visibleEvents() {
    const items = V60.data?.events || [];
    return V60.showFalsePositives ? items : items.filter(item => !isFalsePositiveEvent(item));
  }

  function visibleRecordings() {
    const items = V60.data?.recordings || [];
    if (V60.showFalsePositives) return items;
    const fp = falsePositiveIds();
    return items.filter(rec => String(rec.mode || '') !== 'event' || !rec.source_event_id || !fp.has(Number(rec.source_event_id)));
  }

  function installLegacyCollapse() {
    const view = el('timelineView');
    const legacy = view?.querySelector(':scope > .timeline-panel');
    if (!view || !legacy || el('poiLegacyTimelineDetails')) return;
    const details = document.createElement('details');
    details.id = 'poiLegacyTimelineDetails';
    details.className = 'poi-legacy-timeline';
    details.open = localStorage.getItem('poi.timeline.legacy.open') === '1';
    details.innerHTML = `<summary>
      <span class="poi-legacy-summary-icon">☷</span>
      <span><strong>Lista de eventos</strong><small>Visualização tradicional com filtros e cartões</small></span>
      <span id="poiLegacyCount" class="poi-legacy-count">—</span>
      <span class="poi-legacy-chevron">⌄</span>
    </summary>`;
    legacy.parentNode.insertBefore(details, legacy);
    details.appendChild(legacy);
    legacy.classList.add('poi-legacy-timeline-panel');
    details.addEventListener('toggle', () => localStorage.setItem('poi.timeline.legacy.open', details.open ? '1' : '0'));
  }

  function installPlayer() {
    const view = el('timelineView');
    if (!view || el('poiTimelinePlayer')) return false;
    const legacy = el('poiLegacyTimelineDetails');
    const shell = document.createElement('section');
    shell.id = 'poiTimelinePlayer';
    shell.className = 'poi-day-player panel';
    shell.innerHTML = `
      <div class="poi-day-head"><div><p class="eyebrow">NVR · NAVEGAÇÃO TEMPORAL</p><h2>Timeline do dia</h2><p class="muted paragraph">Vídeo e eventos compartilham a mesma linha do tempo. Quando não houver gravação, o snapshot continua no horário correto.</p></div><div class="poi-day-actions"><button class="button ghost small" id="poiTimelineRefresh" type="button">↻ Atualizar</button><button class="button ghost small" id="poiTimelineNow" type="button">Agora</button></div></div>
      <div class="poi-day-controls"><label><span>Câmera</span><select id="poiTimelineCamera"></select></label><label><span>Data</span><input id="poiTimelineDate" type="date"></label><div id="poiTimelineMode" class="poi-mode-chip">Verificando…</div><label class="poi-fp-toggle"><input id="poiTimelineShowFp" type="checkbox"><span>Mostrar falsos positivos</span></label></div>
      <div class="poi-media-stage" id="poiTimelineStage"><div class="poi-media-topline"><span id="poiMediaTitle">Selecione um horário</span><span id="poiMediaClock">--:--:--</span></div><video id="poiTimelineVideo" controls playsinline preload="metadata" hidden></video><iframe id="poiTimelineLive" title="Câmera ao vivo" allow="autoplay; fullscreen" referrerpolicy="same-origin" hidden></iframe><img id="poiTimelineSnapshot" alt="Snapshot do evento" hidden><div id="poiTimelineEmpty" class="poi-media-empty"><span>◷</span><strong>Escolha um ponto da Timeline</strong><small>Vídeos, clipes de evento e snapshots aparecerão aqui.</small></div><button class="poi-stage-fullscreen" id="poiTimelineFullscreen" type="button" title="Tela cheia">⛶</button></div>
      <div class="poi-timeline-toolbar"><div><strong id="poiTimelineDayLabel">Timeline</strong><span id="poiTimelineHint">Carregando…</span></div><div class="poi-zoom-controls"><span>Zoom</span><button type="button" id="poiZoomOut">−</button><input id="poiZoomRange" type="range" min="1" max="8" step="1" value="${V60.zoom}"><button type="button" id="poiZoomIn">＋</button></div></div>
      <div class="poi-timeline-viewport" id="poiTimelineViewport"><div class="poi-timeline-canvas" id="poiTimelineCanvas"><div class="poi-hour-ruler" id="poiHourRuler"></div><div class="poi-coverage-track" id="poiCoverageTrack"></div><div class="poi-event-markers" id="poiEventMarkers"></div><input id="poiDayScrubber" class="poi-day-scrubber" type="range" min="0" max="86400" step="0.01" value="0" aria-label="Posição no dia"><div id="poiPlayheadLabel" class="poi-playhead-label">00:00:00</div></div></div>
      <div class="poi-event-strip-head"><strong>Eventos do dia</strong><span>Passe o mouse ou toque para ver a miniatura; clique para ir ao horário.</span></div><div id="poiEventStrip" class="poi-event-strip"></div>
      <div class="poi-timeline-legend"><span><i class="poi-legend-video"></i> vídeo contínuo</span><span><i class="poi-legend-event-video"></i> clipe por evento</span><span><i class="poi-legend-event"></i> evento / snapshot</span><span><i class="poi-legend-live"></i> trecho ativo</span></div>`;
    if (legacy) legacy.insertAdjacentElement('afterend', shell); else view.prepend(shell);
    bindPlayerEvents();
    return true;
  }

  function currentRecordingIsVisible() {
    if (!V60.currentRecording) return true;
    return visibleRecordings().some(rec => Number(rec.id) === Number(V60.currentRecording.id));
  }

  function bindPlayerEvents() {
    el('poiTimelineCamera')?.addEventListener('change', event => { V60.cameraId = Number(event.target.value) || null; V60.followLive = false; loadDay({ resetPosition: true }); });
    el('poiTimelineDate')?.addEventListener('change', event => { V60.date = event.target.value || localDateString(); V60.followLive = false; loadDay({ resetPosition: true }); });
    el('poiTimelineRefresh')?.addEventListener('click', () => loadDay({ resetPosition: false }));
    el('poiTimelineNow')?.addEventListener('click', () => { V60.date = localDateString(); if (el('poiTimelineDate')) el('poiTimelineDate').value = V60.date; V60.followLive = true; loadDay({ resetPosition: true, forceLive: true }); });
    el('poiTimelineShowFp')?.addEventListener('change', event => {
      V60.showFalsePositives = Boolean(event.target.checked);
      if (!currentRecordingIsVisible()) { hideMedia(); V60.currentRecording = null; V60.selectedEventId = null; }
      if (V60.selectedEventId && !visibleEvents().some(item => Number(item.id) === Number(V60.selectedEventId))) V60.selectedEventId = null;
      renderCoverage(); renderEvents();
      document.dispatchEvent(new CustomEvent('poi:timeline-filter-changed', { detail: { showFalsePositives: V60.showFalsePositives } }));
    });

    const scrubber = el('poiDayScrubber');
    scrubber?.addEventListener('input', event => { V60.followLive = false; V60.currentSecond = Number(event.target.value) || 0; updatePlayhead(false); });
    scrubber?.addEventListener('change', () => selectSecond(V60.currentSecond, { autoplay: false, scroll: false }));
    el('poiTimelineFullscreen')?.addEventListener('click', () => el('poiTimelineStage')?.requestFullscreen?.().catch(() => {}));
    el('poiZoomOut')?.addEventListener('click', () => setZoom(V60.zoom - 1));
    el('poiZoomIn')?.addEventListener('click', () => setZoom(V60.zoom + 1));
    el('poiZoomRange')?.addEventListener('input', event => setZoom(Number(event.target.value)));

    const video = el('poiTimelineVideo');
    video?.addEventListener('timeupdate', () => {
      if (!V60.currentRecording || video.hidden) return;
      V60.currentSecond = Math.min(Number(V60.data?.day_duration_seconds || 86400), Number(V60.currentRecording.start_second || 0) + Number(video.currentTime || 0));
      updatePlayhead(false);
    });
    video?.addEventListener('ended', playNextSegment);
  }

  async function loadCameras() {
    try { V60.cameras = await api('/api/cameras'); }
    catch (_) { V60.cameras = Array.isArray(window.state?.cameras) ? window.state.cameras : []; }
    const select = el('poiTimelineCamera');
    if (!select) return;
    const usable = V60.cameras.filter(camera => camera.enabled !== false);
    const cameras = usable.length ? usable : V60.cameras;
    if (!V60.cameraId || !cameras.some(camera => Number(camera.id) === Number(V60.cameraId))) V60.cameraId = cameras.length ? Number(cameras[0].id) : null;
    select.innerHTML = cameras.length ? cameras.map(camera => `<option value="${camera.id}" ${Number(camera.id) === Number(V60.cameraId) ? 'selected' : ''}>${q(camera.name)}</option>`).join('') : '<option value="">Nenhuma câmera</option>';
  }

  function cameraForCurrent() { return V60.cameras.find(camera => Number(camera.id) === Number(V60.cameraId)) || null; }

  async function loadDay({ resetPosition = false, forceLive = false } = {}) {
    if (!V60.cameraId || !V60.date) return;
    const token = ++V60.loadToken;
    const offset = -new Date().getTimezoneOffset();
    try {
      const data = await api(`/api/timeline-player/day?camera_id=${encodeURIComponent(V60.cameraId)}&date=${encodeURIComponent(V60.date)}&utc_offset_minutes=${encodeURIComponent(offset)}`);
      if (token !== V60.loadToken) return;
      const previousSecond = V60.currentSecond;
      V60.data = data;
      renderDay();
      const duration = Number(data.day_duration_seconds || 86400);
      if (resetPosition || !Number.isFinite(previousSecond)) {
        const events = visibleEvents(); const recs = visibleRecordings();
        if (forceLive && data.is_today && data.now_second != null) V60.currentSecond = Number(data.now_second);
        else if (data.is_today && data.recording?.mode === 'continuous' && data.now_second != null) { V60.currentSecond = Number(data.now_second); V60.followLive = true; }
        else if (events.length) V60.currentSecond = Number(events[events.length - 1].second || 0);
        else if (recs.length) V60.currentSecond = Number(recs[0].start_second || 0);
        else V60.currentSecond = 0;
        V60.currentSecond = Math.min(duration, Math.max(0, V60.currentSecond));
        await selectSecond(V60.currentSecond, { autoplay: false, scroll: true });
      } else if (V60.followLive && data.is_today && data.now_second != null) {
        V60.currentSecond = Number(data.now_second); await selectSecond(V60.currentSecond, { autoplay: false, scroll: true });
      } else { V60.currentSecond = Math.min(duration, Math.max(0, previousSecond)); updatePlayhead(false); }
      scheduleRefresh();
    } catch (error) {
      if (el('poiTimelineHint')) el('poiTimelineHint').textContent = `Falha ao carregar: ${error.message}`;
      if (typeof toast === 'function') toast(`Timeline: ${error.message}`, 'error');
    }
  }

  function renderDay() {
    const data = V60.data; if (!data) return;
    const mode = String(data.recording?.mode || 'off');
    const chip = el('poiTimelineMode'); if (chip) { chip.textContent = modeLabel(mode); chip.dataset.mode = mode; }
    if (el('poiTimelineDate') && el('poiTimelineDate').value !== V60.date) el('poiTimelineDate').value = V60.date;
    if (el('poiLegacyCount')) el('poiLegacyCount').textContent = `${visibleEvents().length}`;
    if (el('poiTimelineDayLabel')) el('poiTimelineDayLabel').textContent = `${data.camera.name} · ${V60.date.split('-').reverse().join('/')}`;
    const hint = el('poiTimelineHint');
    if (hint) {
      const fp = data.false_positive_count ? ` · ${data.false_positive_count} falso(s) positivo(s) oculto(s)` : '';
      hint.textContent = mode === 'continuous' ? `${visibleRecordings().length} segmento(s) visível(is)${data.is_today ? ' · atualiza em tempo real' : ''}${fp}` : mode === 'event' ? `Somente trechos associados a eventos${fp}` : `Sem vídeo gravado · snapshots permanecem navegáveis${fp}`;
    }
    renderRuler(); renderCoverage(); renderEvents(); setZoom(V60.zoom, false);
    if (el('poiDayScrubber')) { el('poiDayScrubber').max = String(Number(data.day_duration_seconds || 86400)); el('poiDayScrubber').step = '0.01'; }
    if (el('poiTimelineNow')) el('poiTimelineNow').hidden = false;
  }

  function renderRuler() {
    const ruler = el('poiHourRuler'); if (!ruler) return;
    let html = ''; for (let hour = 0; hour <= 24; hour += 2) html += `<span style="left:${(hour / 24) * 100}%"><i></i><b>${String(hour).padStart(2, '0')}:00</b></span>`;
    ruler.innerHTML = html;
  }

  function renderCoverage() {
    const track = el('poiCoverageTrack'); if (!track || !V60.data) return;
    const duration = Number(V60.data.day_duration_seconds || 86400);
    const recs = visibleRecordings();
    track.innerHTML = recs.map(rec => {
      const left = (Number(rec.start_second || 0) / duration) * 100;
      const right = (Number(rec.end_second || 0) / duration) * 100;
      const width = Math.max(.08, right - left);
      const cls = rec.status === 'active' ? ' active' : rec.mode === 'event' ? ' event' : '';
      return `<button type="button" class="poi-coverage${cls}" data-recording-id="${rec.id}" style="left:${left}%;width:${width}%" title="${rec.mode === 'continuous' ? 'Vídeo contínuo' : 'Clipe de evento'} · ${clock(rec.start_second)}–${clock(rec.end_second)}"></button>`;
    }).join('');
    track.querySelectorAll('[data-recording-id]').forEach(node => node.addEventListener('click', event => { event.stopPropagation(); selectRecordingById(Number(node.dataset.recordingId), { autoplay: false, scroll: true }); }));
  }

  function renderEvents() {
    const markers = el('poiEventMarkers'), strip = el('poiEventStrip');
    if (!markers || !strip || !V60.data) return;
    const duration = Number(V60.data.day_duration_seconds || 86400), events = visibleEvents();
    if (el('poiLegacyCount')) el('poiLegacyCount').textContent = `${events.length}`;
    markers.innerHTML = events.map(item => {
      const left = (Number(item.second || 0) / duration) * 100;
      const type = item.person_id ? ' known' : '';
      const media = item.recording_id ? '▶' : item.snapshot_url ? '▧' : '•';
      return `<button type="button" class="poi-event-marker${type}" data-event-id="${item.id}" style="left:${left}%" aria-label="${q(item.label)} às ${clock(item.second)}"><i></i><span class="poi-marker-symbol">${media}</span><span class="poi-event-popover">${item.snapshot_url ? `<img src="${q(item.snapshot_url)}" alt="">` : '<span class="poi-popover-empty">Sem imagem</span>'}<b>${clock(item.second)}</b><strong>${q(item.label)}</strong>${item.recording_id ? '<small>▶ vídeo disponível</small>' : '<small>snapshot</small>'}</span></button>`;
    }).join('');
    strip.innerHTML = events.length ? events.map(item => `<button type="button" class="poi-event-card ${Number(item.id) === Number(V60.selectedEventId) ? 'selected' : ''}" data-event-card="${item.id}"><span class="poi-event-thumb">${item.snapshot_url ? `<img src="${q(item.snapshot_url)}" loading="lazy" alt="">` : '<i>Sem imagem</i>'}<em>${item.recording_id ? '▶' : '▧'}</em></span><span class="poi-event-card-meta"><b>${clock(item.second)}</b><strong>${q(item.label)}</strong><small>${item.recording_id ? (item.recording_mode === 'continuous' ? 'Vídeo contínuo' : 'Clipe de evento') : 'Snapshot'}</small></span></button>`).join('') : '<div class="poi-no-events">Nenhum evento neste dia para esta câmera.</div>';
    markers.querySelectorAll('[data-event-id]').forEach(node => node.addEventListener('click', () => selectEventById(Number(node.dataset.eventId), { autoplay: false, scroll: true })));
    strip.querySelectorAll('[data-event-card]').forEach(node => node.addEventListener('click', () => selectEventById(Number(node.dataset.eventCard), { autoplay: false, scroll: true })));
  }

  function recordingAt(second, event = null) {
    const recordings = visibleRecordings();
    if (event?.recording_id) {
      const exact = recordings.find(rec => Number(rec.id) === Number(event.recording_id));
      if (exact) return exact;
    }
    const candidates = recordings.filter(rec => Number(rec.start_second) <= second && second <= Number(rec.end_second));
    return candidates.find(rec => rec.file_url) || candidates.find(rec => rec.status === 'active') || candidates[0] || null;
  }

  function eventNear(second) {
    const items = visibleEvents(); if (!items.length) return null;
    let best = null, delta = Infinity;
    for (const item of items) { const d = Math.abs(Number(item.second || 0) - second); if (d < delta) { best = item; delta = d; } }
    return delta <= 15 ? best : null;
  }

  function hideMedia() {
    const video = el('poiTimelineVideo'), live = el('poiTimelineLive'), image = el('poiTimelineSnapshot'), empty = el('poiTimelineEmpty');
    if (video) { video.hidden = true; try { video.pause(); } catch (_) {} }
    if (live) { live.hidden = true; if (live.src && live.src !== 'about:blank') live.src = 'about:blank'; }
    if (image) image.hidden = true; if (empty) empty.hidden = true;
  }

  async function selectSecond(second, { event = null, recording = null, autoplay = false, scroll = true } = {}) {
    if (!V60.data) return false;
    const duration = Number(V60.data.day_duration_seconds || 86400);
    V60.currentSecond = Math.min(duration, Math.max(0, Number(second) || 0));
    if (el('poiDayScrubber')) { el('poiDayScrubber').step = '0.01'; el('poiDayScrubber').value = String(V60.currentSecond); }
    updatePlayhead(scroll);

    const rec = recording || recordingAt(V60.currentSecond, event);
    const nearby = event || eventNear(V60.currentSecond);
    hideMedia(); V60.currentRecording = rec;
    if (nearby && visibleEvents().some(item => Number(item.id) === Number(nearby.id))) V60.selectedEventId = Number(nearby.id);
    if (el('poiMediaClock')) el('poiMediaClock').textContent = clock(V60.currentSecond);

    if (rec?.file_url) {
      const video = el('poiTimelineVideo'); if (!video) return false;
      video.hidden = false;
      if (el('poiMediaTitle')) el('poiMediaTitle').textContent = `${V60.data.camera.name} · ${rec.mode === 'continuous' ? 'gravação contínua' : 'clipe de evento'}`;
      const desired = Math.max(0, V60.currentSecond - Number(rec.start_second || 0));
      const same = video.dataset.recordingId === String(rec.id) && Boolean(video.src);
      video.dataset.recordingId = String(rec.id);
      const seek = () => {
        try { video.currentTime = Math.min(Math.max(0, desired), Math.max(0, Number(video.duration || desired) - .05)); } catch (_) {}
        if (autoplay) video.play().catch(() => {});
      };
      if (!same) { video.src = rec.file_url; video.load(); video.addEventListener('loadedmetadata', seek, { once: true }); }
      else seek();
      renderEvents();
      document.dispatchEvent(new CustomEvent('poi:timeline-media-selected', { detail: { type: 'recording', recordingId: Number(rec.id), eventId: rec.source_event_id ? Number(rec.source_event_id) : null, second: V60.currentSecond } }));
      return true;
    }

    if (rec?.status === 'active' && V60.data.is_today) {
      const camera = cameraForCurrent(), live = el('poiTimelineLive');
      if (live && camera?.viewer_url) { live.hidden = false; live.src = typeof resolveViewerUrl === 'function' ? resolveViewerUrl(camera.viewer_url) : camera.viewer_url; if (el('poiMediaTitle')) el('poiMediaTitle').textContent = `${V60.data.camera.name} · ao vivo`; return true; }
    }

    if (nearby?.snapshot_url && visibleEvents().some(item => Number(item.id) === Number(nearby.id))) {
      const image = el('poiTimelineSnapshot'); if (image) { image.hidden = false; image.src = nearby.snapshot_url; }
      if (el('poiMediaTitle')) el('poiMediaTitle').textContent = `${nearby.label} · snapshot do evento`;
      renderEvents();
      document.dispatchEvent(new CustomEvent('poi:timeline-media-selected', { detail: { type: 'event', eventId: Number(nearby.id), second: V60.currentSecond } }));
      return true;
    }

    V60.currentRecording = null;
    if (el('poiTimelineEmpty')) el('poiTimelineEmpty').hidden = false;
    if (el('poiMediaTitle')) el('poiMediaTitle').textContent = 'Sem mídia gravada neste horário';
    document.dispatchEvent(new CustomEvent('poi:timeline-media-selected', { detail: { type: 'empty', second: V60.currentSecond } }));
    return false;
  }

  async function selectRecordingById(recordingId, { autoplay = false, scroll = true, offsetSeconds = 0.02 } = {}) {
    const rec = visibleRecordings().find(item => Number(item.id) === Number(recordingId));
    if (!rec) return false;
    const event = rec.source_event_id ? visibleEvents().find(item => Number(item.id) === Number(rec.source_event_id)) || null : null;
    const start = Number(rec.start_second || 0), end = Number(rec.end_second || start);
    const second = end > start ? Math.min(end - .005, start + Math.max(.005, Number(offsetSeconds) || .02)) : start;
    V60.selectedEventId = event ? Number(event.id) : null; V60.followLive = false;
    return selectSecond(second, { event, recording: rec, autoplay, scroll });
  }

  async function selectEventById(eventId, { autoplay = false, scroll = true } = {}) {
    const event = visibleEvents().find(item => Number(item.id) === Number(eventId));
    if (!event) return false;
    V60.selectedEventId = Number(event.id); V60.followLive = false;
    const rec = event.recording_id ? visibleRecordings().find(item => Number(item.id) === Number(event.recording_id)) || null : null;
    const second = rec ? Math.min(Number(rec.end_second || rec.start_second || 0) - .005, Number(rec.start_second || 0) + .02) : Number(event.second || 0);
    return selectSecond(second, { event, recording: rec, autoplay, scroll });
  }

  function updatePlayhead(scroll = false) {
    if (!V60.data) return;
    const duration = Number(V60.data.day_duration_seconds || 86400);
    const pct = Math.max(0, Math.min(100, (V60.currentSecond / duration) * 100));
    const scrubber = el('poiDayScrubber'); if (scrubber && document.activeElement !== scrubber) { scrubber.step = '0.01'; scrubber.value = String(V60.currentSecond); }
    const label = el('poiPlayheadLabel'); if (label) { label.textContent = clock(V60.currentSecond); label.style.left = `${pct}%`; }
    if (el('poiMediaClock')) el('poiMediaClock').textContent = clock(V60.currentSecond);
    if (scroll) scrollToSecond(V60.currentSecond);
  }

  function setZoom(next, keepCentered = true) {
    V60.zoom = Math.max(1, Math.min(8, Math.round(Number(next) || 1)));
    if (el('poiTimelineCanvas')) el('poiTimelineCanvas').style.width = `${V60.zoom * 100}%`;
    if (el('poiZoomRange')) el('poiZoomRange').value = String(V60.zoom);
    if (keepCentered) requestAnimationFrame(() => scrollToSecond(V60.currentSecond));
  }

  function scrollToSecond(second) {
    const viewport = el('poiTimelineViewport'), canvas = el('poiTimelineCanvas');
    if (!viewport || !canvas || canvas.offsetWidth <= viewport.clientWidth + 2) return;
    const duration = Number(V60.data?.day_duration_seconds || 86400);
    const target = (Math.max(0, Math.min(duration, second)) / duration) * canvas.offsetWidth;
    viewport.scrollTo({ left: Math.max(0, target - viewport.clientWidth / 2), behavior: 'smooth' });
  }

  function playNextSegment() {
    const current = V60.currentRecording; if (!current || current.mode !== 'continuous') return;
    const records = visibleRecordings().filter(rec => rec.mode === 'continuous' && rec.file_url).sort((a, b) => Number(a.start_second) - Number(b.start_second));
    const index = records.findIndex(rec => Number(rec.id) === Number(current.id));
    const next = index >= 0 ? records[index + 1] : null; if (!next) return;
    if (Number(next.start_second) - Number(current.end_second) > 120) return;
    selectRecordingById(next.id, { autoplay: true, scroll: true, offsetSeconds: .05 });
  }

  function scheduleRefresh() {
    clearInterval(V60.refreshTimer); V60.refreshTimer = null;
    if (!V60.data?.is_today) return;
    V60.refreshTimer = setInterval(() => { if (el('timelineView')?.classList.contains('active')) loadDay({ resetPosition: false }); }, 12000);
  }

  window.poiTimelineCore = {
    selectRecordingById, selectEventById, selectSecond,
    getVisibleRecordings: () => visibleRecordings().slice(),
    getVisibleEvents: () => visibleEvents().slice(),
    getCurrentRecordingId: () => Number(V60.currentRecording?.id || 0) || null,
    getCurrentSecond: () => Number(V60.currentSecond || 0),
    isFalsePositiveEvent,
  };

  async function init() {
    installLegacyCollapse(); if (!installPlayer()) return;
    V60.date = localDateString(); if (el('poiTimelineDate')) el('poiTimelineDate').value = V60.date;
    await loadCameras();
    if (V60.cameraId) await loadDay({ resetPosition: true });
    else if (el('poiTimelineHint')) el('poiTimelineHint').textContent = 'Cadastre uma câmera para usar a Timeline.';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true }); else init();
})();