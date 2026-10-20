(() => {
  const V60 = {
    cameras: [],
    data: null,
    cameraId: null,
    date: '',
    currentSecond: 0,
    currentRecording: null,
    selectedEventId: null,
    showFalsePositives: false,
    followLive: false,
    zoom: window.matchMedia('(max-width: 760px)').matches ? 4 : 1,
    refreshTimer: null,
    loadToken: 0,
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

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

  function visibleEvents() {
    const items = V60.data?.events || [];
    return V60.showFalsePositives ? items : items.filter(item => item.identity_state !== 'false_positive');
  }

  function installLegacyCollapse() {
    const view = document.getElementById('timelineView');
    const legacy = view?.querySelector(':scope > .timeline-panel');
    if (!view || !legacy || document.getElementById('poiLegacyTimelineDetails')) return;

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
    details.addEventListener('toggle', () => {
      localStorage.setItem('poi.timeline.legacy.open', details.open ? '1' : '0');
    });
  }

  function installPlayer() {
    const view = document.getElementById('timelineView');
    if (!view || document.getElementById('poiTimelinePlayer')) return false;
    const legacy = document.getElementById('poiLegacyTimelineDetails');
    const shell = document.createElement('section');
    shell.id = 'poiTimelinePlayer';
    shell.className = 'poi-day-player panel';
    shell.innerHTML = `
      <div class="poi-day-head">
        <div>
          <p class="eyebrow">NVR · NAVEGAÇÃO TEMPORAL</p>
          <h2>Timeline do dia</h2>
          <p class="muted paragraph">Vídeo e eventos compartilham a mesma linha do tempo. Quando não houver gravação, o snapshot continua no horário correto.</p>
        </div>
        <div class="poi-day-actions">
          <button class="button ghost small" id="poiTimelineRefresh" type="button">↻ Atualizar</button>
          <button class="button ghost small" id="poiTimelineNow" type="button">Agora</button>
        </div>
      </div>

      <div class="poi-day-controls">
        <label><span>Câmera</span><select id="poiTimelineCamera"></select></label>
        <label><span>Data</span><input id="poiTimelineDate" type="date"></label>
        <div id="poiTimelineMode" class="poi-mode-chip">Verificando…</div>
        <label class="poi-fp-toggle"><input id="poiTimelineShowFp" type="checkbox"><span>Mostrar falsos positivos</span></label>
      </div>

      <div class="poi-media-stage" id="poiTimelineStage">
        <div class="poi-media-topline">
          <span id="poiMediaTitle">Selecione um horário</span>
          <span id="poiMediaClock">--:--:--</span>
        </div>
        <video id="poiTimelineVideo" controls playsinline preload="metadata" hidden></video>
        <iframe id="poiTimelineLive" title="Câmera ao vivo" allow="autoplay; fullscreen" referrerpolicy="same-origin" hidden></iframe>
        <img id="poiTimelineSnapshot" alt="Snapshot do evento" hidden>
        <div id="poiTimelineEmpty" class="poi-media-empty">
          <span>◷</span><strong>Escolha um ponto da Timeline</strong><small>Vídeos, clipes de evento e snapshots aparecerão aqui.</small>
        </div>
        <button class="poi-stage-fullscreen" id="poiTimelineFullscreen" type="button" title="Tela cheia">⛶</button>
      </div>

      <div class="poi-timeline-toolbar">
        <div><strong id="poiTimelineDayLabel">Timeline</strong><span id="poiTimelineHint">Carregando…</span></div>
        <div class="poi-zoom-controls"><span>Zoom</span><button type="button" id="poiZoomOut">−</button><input id="poiZoomRange" type="range" min="1" max="8" step="1" value="${V60.zoom}"><button type="button" id="poiZoomIn">＋</button></div>
      </div>

      <div class="poi-timeline-viewport" id="poiTimelineViewport">
        <div class="poi-timeline-canvas" id="poiTimelineCanvas">
          <div class="poi-hour-ruler" id="poiHourRuler"></div>
          <div class="poi-coverage-track" id="poiCoverageTrack"></div>
          <div class="poi-event-markers" id="poiEventMarkers"></div>
          <input id="poiDayScrubber" class="poi-day-scrubber" type="range" min="0" max="86400" step="1" value="0" aria-label="Posição no dia">
          <div id="poiPlayheadLabel" class="poi-playhead-label">00:00:00</div>
        </div>
      </div>

      <div class="poi-event-strip-head"><strong>Eventos do dia</strong><span>Passe o mouse ou toque para ver a miniatura; clique para ir ao horário.</span></div>
      <div id="poiEventStrip" class="poi-event-strip"></div>

      <div class="poi-timeline-legend">
        <span><i class="poi-legend-video"></i> vídeo contínuo</span>
        <span><i class="poi-legend-event-video"></i> clipe por evento</span>
        <span><i class="poi-legend-event"></i> evento / snapshot</span>
        <span><i class="poi-legend-live"></i> trecho ativo</span>
      </div>`;

    if (legacy) legacy.insertAdjacentElement('afterend', shell);
    else view.prepend(shell);
    bindPlayerEvents();
    return true;
  }

  function bindPlayerEvents() {
    document.getElementById('poiTimelineCamera')?.addEventListener('change', event => {
      V60.cameraId = Number(event.target.value) || null;
      V60.followLive = false;
      loadDay({ resetPosition: true });
    });
    document.getElementById('poiTimelineDate')?.addEventListener('change', event => {
      V60.date = event.target.value || localDateString();
      V60.followLive = false;
      loadDay({ resetPosition: true });
    });
    document.getElementById('poiTimelineRefresh')?.addEventListener('click', () => loadDay({ resetPosition: false }));
    document.getElementById('poiTimelineNow')?.addEventListener('click', () => {
      V60.date = localDateString();
      const input = document.getElementById('poiTimelineDate');
      if (input) input.value = V60.date;
      V60.followLive = true;
      loadDay({ resetPosition: true, forceLive: true });
    });
    document.getElementById('poiTimelineShowFp')?.addEventListener('change', event => {
      V60.showFalsePositives = Boolean(event.target.checked);
      renderEvents();
    });

    const scrubber = document.getElementById('poiDayScrubber');
    scrubber?.addEventListener('input', event => {
      V60.followLive = false;
      V60.currentSecond = Number(event.target.value) || 0;
      updatePlayhead(false);
    });
    scrubber?.addEventListener('change', () => selectSecond(V60.currentSecond, { autoplay: false, scroll: false }));

    document.getElementById('poiTimelineFullscreen')?.addEventListener('click', () => {
      const stage = document.getElementById('poiTimelineStage');
      if (stage?.requestFullscreen) stage.requestFullscreen().catch(() => {});
    });

    document.getElementById('poiZoomOut')?.addEventListener('click', () => setZoom(V60.zoom - 1));
    document.getElementById('poiZoomIn')?.addEventListener('click', () => setZoom(V60.zoom + 1));
    document.getElementById('poiZoomRange')?.addEventListener('input', event => setZoom(Number(event.target.value)));

    const video = document.getElementById('poiTimelineVideo');
    video?.addEventListener('timeupdate', () => {
      if (!V60.currentRecording || video.hidden) return;
      V60.currentSecond = Math.min(
        Number(V60.data?.day_duration_seconds || 86400),
        Number(V60.currentRecording.start_second || 0) + Number(video.currentTime || 0),
      );
      updatePlayhead(false);
    });
    video?.addEventListener('ended', playNextSegment);
  }

  async function loadCameras() {
    try {
      V60.cameras = await api('/api/cameras');
    } catch (_) {
      V60.cameras = Array.isArray(window.state?.cameras) ? window.state.cameras : [];
    }
    const select = document.getElementById('poiTimelineCamera');
    if (!select) return;
    const usable = V60.cameras.filter(camera => camera.enabled !== false);
    const cameras = usable.length ? usable : V60.cameras;
    if (!V60.cameraId || !cameras.some(camera => Number(camera.id) === Number(V60.cameraId))) {
      V60.cameraId = cameras.length ? Number(cameras[0].id) : null;
    }
    select.innerHTML = cameras.length
      ? cameras.map(camera => `<option value="${camera.id}" ${Number(camera.id) === Number(V60.cameraId) ? 'selected' : ''}>${q(camera.name)}</option>`).join('')
      : '<option value="">Nenhuma câmera</option>';
  }

  function cameraForCurrent() {
    return V60.cameras.find(camera => Number(camera.id) === Number(V60.cameraId)) || null;
  }

  async function loadDay({ resetPosition = false, forceLive = false } = {}) {
    if (!V60.cameraId || !V60.date) return;
    const token = ++V60.loadToken;
    const offset = -new Date().getTimezoneOffset();
    const url = `/api/timeline-player/day?camera_id=${encodeURIComponent(V60.cameraId)}&date=${encodeURIComponent(V60.date)}&utc_offset_minutes=${encodeURIComponent(offset)}`;
    try {
      const data = await api(url);
      if (token !== V60.loadToken) return;
      const previousSecond = V60.currentSecond;
      V60.data = data;
      renderDay();

      const duration = Number(data.day_duration_seconds || 86400);
      if (resetPosition || !Number.isFinite(previousSecond)) {
        const normalEvents = visibleEvents();
        if (forceLive && data.is_today && data.now_second != null) {
          V60.currentSecond = Number(data.now_second);
        } else if (data.is_today && data.recording?.mode === 'continuous' && data.now_second != null) {
          V60.currentSecond = Number(data.now_second);
          V60.followLive = true;
        } else if (normalEvents.length) {
          V60.currentSecond = Number(normalEvents[normalEvents.length - 1].second || 0);
        } else if (data.recordings?.length) {
          V60.currentSecond = Number(data.recordings[0].start_second || 0);
        } else {
          V60.currentSecond = 0;
        }
        V60.currentSecond = Math.min(duration, Math.max(0, V60.currentSecond));
        await selectSecond(V60.currentSecond, { autoplay: false, scroll: true });
      } else if (V60.followLive && data.is_today && data.now_second != null) {
        V60.currentSecond = Number(data.now_second);
        await selectSecond(V60.currentSecond, { autoplay: false, scroll: true });
      } else {
        V60.currentSecond = Math.min(duration, Math.max(0, previousSecond));
        updatePlayhead(false);
      }
      scheduleRefresh();
    } catch (error) {
      const hint = document.getElementById('poiTimelineHint');
      if (hint) hint.textContent = `Falha ao carregar: ${error.message}`;
      if (typeof toast === 'function') toast(`Timeline: ${error.message}`, 'error');
    }
  }

  function renderDay() {
    const data = V60.data;
    if (!data) return;
    const mode = String(data.recording?.mode || 'off');
    const chip = document.getElementById('poiTimelineMode');
    if (chip) {
      chip.textContent = modeLabel(mode);
      chip.dataset.mode = mode;
    }
    const date = document.getElementById('poiTimelineDate');
    if (date && date.value !== V60.date) date.value = V60.date;
    const summaryCount = document.getElementById('poiLegacyCount');
    if (summaryCount) summaryCount.textContent = `${visibleEvents().length}`;
    const label = document.getElementById('poiTimelineDayLabel');
    if (label) label.textContent = `${data.camera.name} · ${V60.date.split('-').reverse().join('/')}`;
    const hint = document.getElementById('poiTimelineHint');
    if (hint) {
      const fp = data.false_positive_count ? ` · ${data.false_positive_count} falso(s) positivo(s) oculto(s)` : '';
      hint.textContent = mode === 'continuous'
        ? `${data.recordings.length} segmento(s) indexado(s)${data.is_today ? ' · atualiza em tempo real' : ''}${fp}`
        : mode === 'event'
          ? `Somente trechos associados a eventos${fp}`
          : `Sem vídeo gravado · snapshots permanecem navegáveis${fp}`;
    }
    renderRuler();
    renderCoverage();
    renderEvents();
    setZoom(V60.zoom, false);
    const scrubber = document.getElementById('poiDayScrubber');
    if (scrubber) scrubber.max = String(Math.round(Number(data.day_duration_seconds || 86400)));
    const nowButton = document.getElementById('poiTimelineNow');
    if (nowButton) nowButton.hidden = false;
  }

  function renderRuler() {
    const ruler = document.getElementById('poiHourRuler');
    if (!ruler) return;
    let html = '';
    for (let hour = 0; hour <= 24; hour += 2) {
      const left = (hour / 24) * 100;
      html += `<span style="left:${left}%"><i></i><b>${String(hour).padStart(2, '0')}:00</b></span>`;
    }
    ruler.innerHTML = html;
  }

  function renderCoverage() {
    const track = document.getElementById('poiCoverageTrack');
    if (!track || !V60.data) return;
    const duration = Number(V60.data.day_duration_seconds || 86400);
    track.innerHTML = (V60.data.recordings || []).map(rec => {
      const left = (Number(rec.start_second || 0) / duration) * 100;
      const right = (Number(rec.end_second || 0) / duration) * 100;
      const width = Math.max(.08, right - left);
      const cls = rec.status === 'active' ? ' active' : rec.mode === 'event' ? ' event' : '';
      return `<button type="button" class="poi-coverage${cls}" data-recording-id="${rec.id}" style="left:${left}%;width:${width}%" title="${rec.mode === 'continuous' ? 'Vídeo contínuo' : 'Clipe de evento'} · ${clock(rec.start_second)}–${clock(rec.end_second)}"></button>`;
    }).join('');
    track.querySelectorAll('[data-recording-id]').forEach(el => el.addEventListener('click', event => {
      event.stopPropagation();
      const rec = (V60.data.recordings || []).find(item => Number(item.id) === Number(el.dataset.recordingId));
      if (rec) selectSecond(Number(rec.start_second || 0) + .2, { autoplay: false, scroll: true });
    }));
  }

  function renderEvents() {
    const markers = document.getElementById('poiEventMarkers');
    const strip = document.getElementById('poiEventStrip');
    if (!markers || !strip || !V60.data) return;
    const duration = Number(V60.data.day_duration_seconds || 86400);
    const events = visibleEvents();
    const summaryCount = document.getElementById('poiLegacyCount');
    if (summaryCount) summaryCount.textContent = `${events.length}`;

    markers.innerHTML = events.map(item => {
      const left = (Number(item.second || 0) / duration) * 100;
      const type = item.identity_state === 'false_positive' ? ' fp' : item.person_id ? ' known' : '';
      const media = item.recording_id ? '▶' : item.snapshot_url ? '▧' : '•';
      return `<button type="button" class="poi-event-marker${type}" data-event-id="${item.id}" style="left:${left}%" aria-label="${q(item.label)} às ${clock(item.second)}">
        <i></i><span class="poi-marker-symbol">${media}</span>
        <span class="poi-event-popover">${item.snapshot_url ? `<img src="${q(item.snapshot_url)}" alt="">` : '<span class="poi-popover-empty">Sem imagem</span>'}<b>${clock(item.second)}</b><strong>${q(item.label)}</strong>${item.recording_id ? '<small>▶ vídeo disponível</small>' : '<small>snapshot</small>'}</span>
      </button>`;
    }).join('');

    strip.innerHTML = events.length ? events.map(item => `
      <button type="button" class="poi-event-card ${Number(item.id) === Number(V60.selectedEventId) ? 'selected' : ''}" data-event-card="${item.id}">
        <span class="poi-event-thumb">${item.snapshot_url ? `<img src="${q(item.snapshot_url)}" loading="lazy" alt="">` : '<i>Sem imagem</i>'}<em>${item.recording_id ? '▶' : '▧'}</em></span>
        <span class="poi-event-card-meta"><b>${clock(item.second)}</b><strong>${q(item.label)}</strong><small>${item.recording_id ? (item.recording_mode === 'continuous' ? 'Vídeo contínuo' : 'Clipe de evento') : 'Snapshot'}</small></span>
      </button>`).join('') : '<div class="poi-no-events">Nenhum evento neste dia para esta câmera.</div>';

    const choose = id => {
      const item = events.find(event => Number(event.id) === Number(id));
      if (!item) return;
      V60.selectedEventId = item.id;
      V60.followLive = false;
      renderEvents();
      selectSecond(Number(item.second || 0), { event: item, autoplay: false, scroll: true });
    };
    markers.querySelectorAll('[data-event-id]').forEach(el => el.addEventListener('click', () => choose(el.dataset.eventId)));
    strip.querySelectorAll('[data-event-card]').forEach(el => el.addEventListener('click', () => choose(el.dataset.eventCard)));
  }

  function recordingAt(second, event = null) {
    const recordings = V60.data?.recordings || [];
    if (event?.recording_id) {
      const exact = recordings.find(rec => Number(rec.id) === Number(event.recording_id));
      if (exact) return exact;
    }
    const candidates = recordings.filter(rec => Number(rec.start_second) <= second && second <= Number(rec.end_second));
    return candidates.find(rec => rec.file_url) || candidates.find(rec => rec.status === 'active') || candidates[0] || null;
  }

  function eventNear(second) {
    const items = visibleEvents();
    if (!items.length) return null;
    let best = null;
    let delta = Infinity;
    for (const item of items) {
      const d = Math.abs(Number(item.second || 0) - second);
      if (d < delta) { best = item; delta = d; }
    }
    return delta <= 15 ? best : null;
  }

  function hideMedia() {
    const video = document.getElementById('poiTimelineVideo');
    const live = document.getElementById('poiTimelineLive');
    const image = document.getElementById('poiTimelineSnapshot');
    const empty = document.getElementById('poiTimelineEmpty');
    if (video) { video.hidden = true; video.pause(); }
    if (live) { live.hidden = true; if (live.src && live.src !== 'about:blank') live.src = 'about:blank'; }
    if (image) image.hidden = true;
    if (empty) empty.hidden = true;
  }

  async function selectSecond(second, { event = null, autoplay = false, scroll = true } = {}) {
    if (!V60.data) return;
    const duration = Number(V60.data.day_duration_seconds || 86400);
    V60.currentSecond = Math.min(duration, Math.max(0, Number(second) || 0));
    const scrubber = document.getElementById('poiDayScrubber');
    if (scrubber) scrubber.value = String(Math.round(V60.currentSecond));
    updatePlayhead(scroll);

    const rec = recordingAt(V60.currentSecond, event);
    const nearby = event || eventNear(V60.currentSecond);
    hideMedia();
    V60.currentRecording = rec;

    const title = document.getElementById('poiMediaTitle');
    const mediaClock = document.getElementById('poiMediaClock');
    if (mediaClock) mediaClock.textContent = clock(V60.currentSecond);

    if (rec?.file_url) {
      const video = document.getElementById('poiTimelineVideo');
      if (!video) return;
      video.hidden = false;
      if (title) title.textContent = `${V60.data.camera.name} · ${rec.mode === 'continuous' ? 'gravação contínua' : 'clipe de evento'}`;
      const desired = Math.max(0, V60.currentSecond - Number(rec.start_second || 0));
      const same = video.dataset.recordingId === String(rec.id) && video.src;
      video.dataset.recordingId = String(rec.id);
      if (!same) {
        video.src = rec.file_url;
        video.load();
        const seek = () => {
          try { video.currentTime = Math.min(Math.max(0, desired), Math.max(0, Number(video.duration || desired) - .05)); } catch (_) {}
          if (autoplay) video.play().catch(() => {});
          video.removeEventListener('loadedmetadata', seek);
        };
        video.addEventListener('loadedmetadata', seek);
      } else {
        try { video.currentTime = desired; } catch (_) {}
        if (autoplay) video.play().catch(() => {});
      }
      return;
    }

    if (rec?.status === 'active' && V60.data.is_today) {
      const camera = cameraForCurrent();
      const live = document.getElementById('poiTimelineLive');
      if (live && camera?.viewer_url) {
        live.hidden = false;
        live.src = typeof resolveViewerUrl === 'function' ? resolveViewerUrl(camera.viewer_url) : camera.viewer_url;
        if (title) title.textContent = `${V60.data.camera.name} · ao vivo`;
        return;
      }
    }

    if (nearby?.snapshot_url) {
      const image = document.getElementById('poiTimelineSnapshot');
      if (image) {
        image.hidden = false;
        image.src = nearby.snapshot_url;
      }
      if (title) title.textContent = `${nearby.label} · snapshot do evento`;
      return;
    }

    const empty = document.getElementById('poiTimelineEmpty');
    if (empty) empty.hidden = false;
    if (title) title.textContent = 'Sem mídia gravada neste horário';
  }

  function updatePlayhead(scroll = false) {
    const data = V60.data;
    if (!data) return;
    const duration = Number(data.day_duration_seconds || 86400);
    const pct = Math.max(0, Math.min(100, (V60.currentSecond / duration) * 100));
    const scrubber = document.getElementById('poiDayScrubber');
    if (scrubber && document.activeElement !== scrubber) scrubber.value = String(Math.round(V60.currentSecond));
    const label = document.getElementById('poiPlayheadLabel');
    if (label) {
      label.textContent = clock(V60.currentSecond);
      label.style.left = `${pct}%`;
    }
    const mediaClock = document.getElementById('poiMediaClock');
    if (mediaClock) mediaClock.textContent = clock(V60.currentSecond);
    if (scroll) scrollToSecond(V60.currentSecond);
  }

  function setZoom(next, keepCentered = true) {
    V60.zoom = Math.max(1, Math.min(8, Math.round(Number(next) || 1)));
    const canvas = document.getElementById('poiTimelineCanvas');
    const range = document.getElementById('poiZoomRange');
    if (canvas) canvas.style.width = `${V60.zoom * 100}%`;
    if (range) range.value = String(V60.zoom);
    if (keepCentered) requestAnimationFrame(() => scrollToSecond(V60.currentSecond));
  }

  function scrollToSecond(second) {
    const viewport = document.getElementById('poiTimelineViewport');
    const canvas = document.getElementById('poiTimelineCanvas');
    if (!viewport || !canvas || canvas.offsetWidth <= viewport.clientWidth + 2) return;
    const duration = Number(V60.data?.day_duration_seconds || 86400);
    const target = (Math.max(0, Math.min(duration, second)) / duration) * canvas.offsetWidth;
    viewport.scrollTo({ left: Math.max(0, target - viewport.clientWidth / 2), behavior: 'smooth' });
  }

  function playNextSegment() {
    const current = V60.currentRecording;
    if (!current || current.mode !== 'continuous') return;
    const records = (V60.data?.recordings || []).filter(rec => rec.mode === 'continuous' && rec.file_url);
    const index = records.findIndex(rec => Number(rec.id) === Number(current.id));
    const next = index >= 0 ? records[index + 1] : null;
    if (!next) return;
    const gap = Number(next.start_second) - Number(current.end_second);
    if (gap > 120) return;
    selectSecond(Number(next.start_second) + .05, { autoplay: true, scroll: true });
  }

  function scheduleRefresh() {
    clearInterval(V60.refreshTimer);
    V60.refreshTimer = null;
    if (!V60.data?.is_today) return;
    V60.refreshTimer = setInterval(() => {
      const view = document.getElementById('timelineView');
      if (!view?.classList.contains('active')) return;
      loadDay({ resetPosition: false });
    }, 12000);
  }

  async function init() {
    installLegacyCollapse();
    if (!installPlayer()) return;
    V60.date = localDateString();
    const date = document.getElementById('poiTimelineDate');
    if (date) date.value = V60.date;
    await loadCameras();
    if (V60.cameraId) await loadDay({ resetPosition: true });
    else {
      const hint = document.getElementById('poiTimelineHint');
      if (hint) hint.textContent = 'Cadastre uma câmera para usar a Timeline.';
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
