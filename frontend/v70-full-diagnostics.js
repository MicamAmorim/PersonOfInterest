(() => {
  const nativeFetch = window.fetch.bind(window);
  const D = {
    sessionId: null,
    active: false,
    mode: 'full',
    startedAt: 0,
    queue: [],
    flushTimer: null,
    stateTimer: null,
    sampleTimer: null,
    elapsedTimer: null,
    mediaScanTimer: null,
    rafHandle: null,
    rafFrames: 0,
    rafWindowStart: 0,
    observers: [],
    boundMedia: new WeakSet(),
    fetchPatched: false,
    screenStream: null,
    screenRecorder: null,
    screenChunks: [],
    screenUploadPromise: null,
    stopping: false,
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function nowIso() { return new Date().toISOString(); }

  function safeUrl(raw) {
    try {
      const url = new URL(String(raw || ''), location.href);
      const safe = new URL(url.pathname, location.origin);
      for (const [key, value] of url.searchParams.entries()) {
        const lower = key.toLowerCase();
        if (['endpoint', 'token', 'password', 'passwd', 'secret', 'authorization', 'rtsp', 'url'].some(x => lower.includes(x))) {
          safe.searchParams.set(key, '<redacted>');
        } else {
          safe.searchParams.set(key, String(value).slice(0, 160));
        }
      }
      return `${safe.pathname}${safe.search}`;
    } catch (_) {
      return String(raw || '').split('?')[0].slice(0, 300);
    }
  }

  function compactData(value, depth = 0) {
    if (depth > 5) return '<max-depth>';
    if (value == null || typeof value === 'number' || typeof value === 'boolean') return value;
    if (typeof value === 'string') return value.length > 800 ? `${value.slice(0, 800)}…` : value;
    if (Array.isArray(value)) return value.slice(0, 100).map(item => compactData(item, depth + 1));
    if (typeof value === 'object') {
      const out = {};
      for (const [key, val] of Object.entries(value)) {
        const lower = key.toLowerCase();
        if (['password', 'token', 'secret', 'credential', 'embedding', 'rtsp', 'authorization'].some(x => lower.includes(x))) out[key] = '<redacted>';
        else out[key] = compactData(val, depth + 1);
      }
      return out;
    }
    return String(value);
  }

  function log(category, kind, data = {}) {
    if (!D.active || !D.sessionId) return;
    D.queue.push({ category, kind, ts: nowIso(), data: compactData(data) });
    if (D.queue.length >= 30) flush();
  }

  async function flush() {
    if (!D.sessionId || !D.queue.length) return;
    const batch = D.queue.splice(0, Math.min(200, D.queue.length));
    try {
      await nativeFetch(`/api/diagnostics/session/${encodeURIComponent(D.sessionId)}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: batch }),
        keepalive: true,
      });
    } catch (_) {
      D.queue.unshift(...batch.slice(-100));
    }
  }

  function patchFetch() {
    if (D.fetchPatched) return;
    D.fetchPatched = true;
    window.fetch = async function poiDiagnosticFetch(input, init) {
      const rawUrl = typeof input === 'string' ? input : input?.url;
      if (!D.active || String(rawUrl || '').includes('/api/diagnostics/session/')) return nativeFetch(input, init);
      const started = performance.now();
      const method = String(init?.method || input?.method || 'GET').toUpperCase();
      try {
        const response = await nativeFetch(input, init);
        log('api', 'api.request', {
          method,
          url: safeUrl(rawUrl),
          status: response.status,
          ok: response.ok,
          duration_ms: Math.round((performance.now() - started) * 10) / 10,
          content_length: Number(response.headers.get('content-length') || 0) || null,
        });
        return response;
      } catch (error) {
        log('api', 'api.request_error', {
          method,
          url: safeUrl(rawUrl),
          duration_ms: Math.round((performance.now() - started) * 10) / 10,
          error: String(error?.message || error),
        });
        throw error;
      }
    };
  }

  function targetInfo(target) {
    const el = target?.closest?.('button,a,[role="button"],[data-event-id],[data-event-card],[data-v66-session-id],select,input') || target;
    if (!el) return {};
    const dataset = {};
    for (const [key, value] of Object.entries(el.dataset || {})) {
      if (/id|event|recording|camera|audio|session|action/i.test(key)) dataset[key] = String(value).slice(0, 120);
    }
    return {
      tag: String(el.tagName || '').toLowerCase(),
      id: el.id || null,
      role: el.getAttribute?.('role') || null,
      aria_label: el.getAttribute?.('aria-label') || null,
      type: el.getAttribute?.('type') || null,
      dataset,
    };
  }

  function semanticAction(target) {
    const id = target?.closest?.('[id]')?.id || target?.id || '';
    const map = {
      poiHybridPrev: 'timeline.previous_media',
      poiHybridBack: 'timeline.seek_back_10',
      poiHybridPlay: 'timeline.toggle_playback',
      poiHybridForward: 'timeline.seek_forward_10',
      poiHybridNext: 'timeline.next_media',
      poiTimelineRefresh: 'timeline.refresh',
      poiTimelineClassify: 'timeline.classification_open',
      poiClassifyIdentify: 'timeline.identify_person',
      poiClassifyPersonSave: 'timeline.classification_save',
      poiClassifyFalsePositive: 'timeline.false_positive',
      poiClassifyDelete: 'timeline.delete_event',
    };
    if (map[id]) return map[id];
    if (target?.closest?.('#poiV66AudioTrack [data-v66-session-id]')) return 'timeline.tonho_select';
    if (target?.closest?.('#poiEventMarkers [data-event-id]')) return 'timeline.event_marker_select';
    if (target?.closest?.('#poiEventStrip [data-event-card]')) return 'timeline.event_card_select';
    if (target?.closest?.('[data-recording-id]')) return 'timeline.recording_select';
    return id ? `ui.click.${id}` : 'ui.click';
  }

  function actionContext(target) {
    const scrubber = document.getElementById('poiDayScrubber');
    const personSelect = document.getElementById('poiClassifyPersonSelect');
    return {
      target: targetInfo(target),
      view: document.querySelector('.view.active')?.id || null,
      timeline: {
        camera_id: Number(document.getElementById('poiTimelineCamera')?.value || 0) || null,
        date: document.getElementById('poiTimelineDate')?.value || null,
        second: scrubber ? Number(scrubber.value || 0) : null,
        selected_person_id: personSelect && personSelect.value !== 'new' ? Number(personSelect.value || 0) || null : null,
        classifying_event_id: Number(document.getElementById('poiTimelineClassifyDialog')?.dataset?.eventId || 0) || null,
      },
    };
  }

  function installActionCapture() {
    if (document.documentElement.dataset.poiV70Actions === '1') return;
    document.documentElement.dataset.poiV70Actions = '1';
    document.addEventListener('click', event => {
      if (!D.active) return;
      log('frontend-actions', semanticAction(event.target), actionContext(event.target));
    }, true);
    document.addEventListener('change', event => {
      if (!D.active) return;
      const target = event.target;
      const safeValue = target?.type === 'checkbox' ? Boolean(target.checked)
        : (/camera|date|speed|mode|limit/i.test(target?.id || '') ? String(target?.value || '').slice(0, 120) : '<not-recorded>');
      log('frontend-actions', `ui.change.${target?.id || target?.name || 'control'}`, {
        target: targetInfo(target), value: safeValue,
      });
    }, true);
  }

  function mediaData(el) {
    let quality = null;
    try {
      if (typeof el.getVideoPlaybackQuality === 'function') {
        const qv = el.getVideoPlaybackQuality();
        quality = { total_frames: qv.totalVideoFrames, dropped_frames: qv.droppedVideoFrames, corrupted_frames: qv.corruptedVideoFrames };
      }
    } catch (_) {}
    const ranges = [];
    try {
      for (let i = Math.max(0, el.buffered.length - 3); i < el.buffered.length; i += 1) ranges.push([el.buffered.start(i), el.buffered.end(i)]);
    } catch (_) {}
    return {
      id: el.id || null,
      tag: String(el.tagName || '').toLowerCase(),
      src: safeUrl(el.currentSrc || el.src || ''),
      current_time: Number(el.currentTime || 0),
      duration: Number.isFinite(el.duration) ? Number(el.duration) : null,
      paused: Boolean(el.paused),
      ended: Boolean(el.ended),
      ready_state: el.readyState,
      network_state: el.networkState,
      playback_rate: el.playbackRate,
      buffered: ranges,
      video_width: el.videoWidth || null,
      video_height: el.videoHeight || null,
      recording_id: Number(el.dataset?.recordingId || 0) || null,
      quality,
    };
  }

  function bindMedia() {
    document.querySelectorAll('video,audio').forEach(el => {
      if (D.boundMedia.has(el)) return;
      D.boundMedia.add(el);
      ['play', 'pause', 'playing', 'waiting', 'stalled', 'seeking', 'seeked', 'ended', 'error', 'loadedmetadata', 'canplay', 'ratechange', 'emptied'].forEach(name => {
        el.addEventListener(name, () => {
          if (!D.active) return;
          const data = mediaData(el);
          if (name === 'error') data.media_error = el.error ? { code: el.error.code, message: el.error.message || null } : null;
          log('media', `media.${name}`, data);
        });
      });
    });
  }

  function stateSnapshot() {
    const video = document.getElementById('poiTimelineVideo');
    const scrubber = document.getElementById('poiDayScrubber');
    const selectedEvent = document.querySelector('#poiEventMarkers .selected[data-event-id],#poiEventStrip .selected[data-event-card]');
    const selectedTonho = document.querySelector('#poiV66AudioTrack .selected[data-v66-session-id],[data-v66-session-id][aria-pressed="true"]');
    return {
      view: document.querySelector('.view.active')?.id || null,
      visibility: document.visibilityState,
      viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio || 1 },
      timeline: {
        camera_id: Number(document.getElementById('poiTimelineCamera')?.value || 0) || null,
        date: document.getElementById('poiTimelineDate')?.value || null,
        second: scrubber ? Number(scrubber.value || 0) : null,
        selected_event_id: Number(selectedEvent?.dataset?.eventId || selectedEvent?.dataset?.eventCard || 0) || null,
        selected_tonho_id: selectedTonho?.dataset?.v66SessionId || null,
        classify_visible: document.getElementById('poiTimelineClassify') ? !document.getElementById('poiTimelineClassify').hidden : null,
        empty_placeholder_visible: (() => {
          const el = document.querySelector('#poiTimelineStage .poi-timeline-empty,#poiTimelineEmpty');
          return el ? !el.hidden && getComputedStyle(el).display !== 'none' : null;
        })(),
        hybrid_status: document.getElementById('poiHybridStatus')?.textContent || null,
        tonho_overlay_visible: (() => { const el = document.getElementById('poiV66AudioOverlay'); return el ? !el.hidden && getComputedStyle(el).display !== 'none' : false; })(),
        bbox_visible: (() => { const el = document.getElementById('poiV66BBox'); return el ? !el.hidden && getComputedStyle(el).display !== 'none' : false; })(),
      },
      media: video ? mediaData(video) : null,
      dialogs_open: Array.from(document.querySelectorAll('dialog[open]')).map(el => el.id || '<dialog>').slice(0, 10),
    };
  }

  function perfSnapshot() {
    const memory = performance.memory ? {
      used_js_heap_bytes: performance.memory.usedJSHeapSize,
      total_js_heap_bytes: performance.memory.totalJSHeapSize,
      js_heap_limit_bytes: performance.memory.jsHeapSizeLimit,
    } : null;
    const connection = navigator.connection ? {
      effective_type: navigator.connection.effectiveType,
      downlink_mbps: navigator.connection.downlink,
      rtt_ms: navigator.connection.rtt,
      save_data: navigator.connection.saveData,
    } : null;
    const video = document.getElementById('poiTimelineVideo');
    return { memory, connection, media_quality: video ? mediaData(video).quality : null };
  }

  function startPerformanceObservers() {
    stopPerformanceObservers();
    if (typeof PerformanceObserver === 'function') {
      try {
        const longTask = new PerformanceObserver(list => {
          for (const entry of list.getEntries()) log('performance', 'performance.long_task', { start_ms: entry.startTime, duration_ms: entry.duration, name: entry.name });
        });
        longTask.observe({ type: 'longtask', buffered: true });
        D.observers.push(longTask);
      } catch (_) {}
      try {
        const layout = new PerformanceObserver(list => {
          for (const entry of list.getEntries()) if (!entry.hadRecentInput) log('performance', 'performance.layout_shift', { start_ms: entry.startTime, value: entry.value });
        });
        layout.observe({ type: 'layout-shift', buffered: true });
        D.observers.push(layout);
      } catch (_) {}
    }
    D.rafFrames = 0;
    D.rafWindowStart = performance.now();
    const frame = now => {
      if (!D.active) return;
      D.rafFrames += 1;
      const elapsed = now - D.rafWindowStart;
      if (elapsed >= 2000) {
        log('performance', 'performance.raf_fps', { fps: Math.round((D.rafFrames * 10000) / elapsed) / 10, ...perfSnapshot() });
        D.rafFrames = 0;
        D.rafWindowStart = now;
      }
      D.rafHandle = requestAnimationFrame(frame);
    };
    D.rafHandle = requestAnimationFrame(frame);
  }

  function stopPerformanceObservers() {
    D.observers.forEach(observer => { try { observer.disconnect(); } catch (_) {} });
    D.observers = [];
    if (D.rafHandle) cancelAnimationFrame(D.rafHandle);
    D.rafHandle = null;
  }

  function installErrorCapture() {
    if (document.documentElement.dataset.poiV70Errors === '1') return;
    document.documentElement.dataset.poiV70Errors = '1';
    window.addEventListener('error', event => {
      log('errors', 'window.error', { message: event.message, filename: safeUrl(event.filename), lineno: event.lineno, colno: event.colno, stack: String(event.error?.stack || '').slice(0, 6000) });
    });
    window.addEventListener('unhandledrejection', event => {
      log('errors', 'window.unhandledrejection', { reason: String(event.reason?.stack || event.reason || '').slice(0, 6000) });
    });
  }

  function clientInfo() {
    return {
      user_agent: navigator.userAgent,
      language: navigator.language,
      platform: navigator.platform,
      standalone: Boolean(window.matchMedia?.('(display-mode: standalone)')?.matches),
      screen: { width: screen.width, height: screen.height, color_depth: screen.colorDepth },
      viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio || 1 },
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      hardware_concurrency: navigator.hardwareConcurrency || null,
      device_memory_gb: navigator.deviceMemory || null,
    };
  }

  async function apiJson(url, init = {}) {
    const response = await nativeFetch(url, init);
    if (!response.ok) {
      let detail = `${response.status}`;
      try { const body = await response.json(); detail = body.detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  }

  async function prepareScreenStream() {
    if (!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder === 'undefined') throw new Error('Gravação de tela não suportada neste navegador/PWA.');
    return navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 15 }, audio: false });
  }

  function startScreenRecorder(stream) {
    if (!stream || !D.sessionId) return;
    const candidates = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    const mimeType = candidates.find(type => !MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(type)) || '';
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 1600000 } : { videoBitsPerSecond: 1600000 });
    D.screenStream = stream;
    D.screenRecorder = recorder;
    D.screenChunks = [];
    recorder.addEventListener('dataavailable', event => { if (event.data?.size) D.screenChunks.push(event.data); });
    recorder.addEventListener('stop', () => {
      const blob = new Blob(D.screenChunks, { type: recorder.mimeType || 'video/webm' });
      D.screenChunks = [];
      if (!D.sessionId || !blob.size) return;
      D.screenUploadPromise = nativeFetch(`/api/diagnostics/session/${encodeURIComponent(D.sessionId)}/screen`, {
        method: 'POST', headers: { 'Content-Type': blob.type || 'video/webm' }, body: blob,
      }).then(response => { if (!response.ok) throw new Error(`Upload da tela: ${response.status}`); })
        .catch(error => log('errors', 'screen.upload_error', { error: String(error?.message || error), bytes: blob.size }));
    });
    stream.getVideoTracks()[0]?.addEventListener('ended', () => {
      if (recorder.state !== 'inactive') recorder.stop();
      log('frontend-actions', 'screen.sharing_ended', {});
    });
    recorder.start(1000);
  }

  async function stopScreenRecorder() {
    const recorder = D.screenRecorder;
    if (recorder && recorder.state !== 'inactive') {
      await new Promise(resolve => {
        recorder.addEventListener('stop', resolve, { once: true });
        recorder.stop();
      });
    }
    D.screenStream?.getTracks().forEach(track => { try { track.stop(); } catch (_) {} });
    if (D.screenUploadPromise) await D.screenUploadPromise;
    D.screenRecorder = null;
    D.screenStream = null;
    D.screenUploadPromise = null;
  }

  function startTimers() {
    clearTimers();
    const full = D.mode === 'full';
    D.flushTimer = setInterval(flush, 1000);
    D.stateTimer = setInterval(() => log('frontend-state', 'frontend.state', stateSnapshot()), full ? 1000 : 3000);
    D.sampleTimer = setInterval(() => {
      if (!D.active || !D.sessionId) return;
      nativeFetch(`/api/diagnostics/session/${encodeURIComponent(D.sessionId)}/sample`, { method: 'POST' })
        .catch(error => log('errors', 'backend.sample_error', { error: String(error?.message || error) }));
    }, full ? 2000 : 5000);
    D.mediaScanTimer = setInterval(bindMedia, 1000);
    D.elapsedTimer = setInterval(renderStatus, 1000);
  }

  function clearTimers() {
    ['flushTimer', 'stateTimer', 'sampleTimer', 'mediaScanTimer', 'elapsedTimer'].forEach(key => {
      if (D[key]) clearInterval(D[key]);
      D[key] = null;
    });
  }

  function beginInstrumentation() {
    patchFetch();
    installActionCapture();
    installErrorCapture();
    bindMedia();
    startPerformanceObservers();
    startTimers();
    log('frontend-actions', 'diagnostic.session_started', { mode: D.mode, state: stateSnapshot() });
  }

  async function startSession() {
    if (D.active || D.stopping) return;
    const mode = document.getElementById('poiV70Mode')?.value || 'full';
    const wantsScreen = Boolean(document.getElementById('poiV70Screen')?.checked);
    const includeTonhoText = Boolean(document.getElementById('poiV70TonhoText')?.checked);
    let screenStream = null;
    if (wantsScreen) {
      try { screenStream = await prepareScreenStream(); }
      catch (error) {
        if (!confirm(`Não foi possível iniciar a gravação de tela (${error.message}). Continuar o diagnóstico sem vídeo?`)) return;
      }
    }
    try {
      const result = await apiJson('/api/diagnostics/session/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, screen_recording: Boolean(screenStream), include_tonho_text: includeTonhoText, client: clientInfo() }),
      });
      D.sessionId = result.session_id;
      D.active = true;
      D.mode = result.mode || mode;
      D.startedAt = Date.now();
      if (screenStream) startScreenRecorder(screenStream);
      beginInstrumentation();
      renderStatus();
    } catch (error) {
      screenStream?.getTracks().forEach(track => track.stop());
      alert(`Não foi possível iniciar o diagnóstico: ${error.message}`);
    }
  }

  async function markProblem() {
    if (!D.active || !D.sessionId) return;
    const note = prompt('O que você percebeu neste instante? (opcional)', '') ?? '';
    log('markers', 'user.problem_marker.client', { note: note.slice(0, 500), state: stateSnapshot() });
    try {
      await apiJson(`/api/diagnostics/session/${encodeURIComponent(D.sessionId)}/marker`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }),
      });
      if (typeof toast === 'function') toast('Problema marcado no diagnóstico.');
    } catch (error) {
      if (typeof toast === 'function') toast(`Marcador: ${error.message}`, 'error');
    }
  }

  async function stopAndExport() {
    if (!D.active || !D.sessionId || D.stopping) return;
    D.stopping = true;
    const sessionId = D.sessionId;
    try {
      log('frontend-actions', 'diagnostic.stop_requested', { state: stateSnapshot() });
      await flush();
      await stopScreenRecorder();
      await flush();
      const result = await apiJson(`/api/diagnostics/session/${encodeURIComponent(sessionId)}/stop`, { method: 'POST' });
      D.active = false;
      clearTimers();
      stopPerformanceObservers();
      D.sessionId = null;
      renderStatus();
      window.location.href = result.export_url;
      setTimeout(loadServerStatus, 1200);
    } catch (error) {
      alert(`Não foi possível encerrar/exportar: ${error.message}`);
    } finally {
      D.stopping = false;
    }
  }

  function elapsedLabel() {
    if (!D.active || !D.startedAt) return '—';
    const s = Math.max(0, Math.floor((Date.now() - D.startedAt) / 1000));
    const m = Math.floor(s / 60);
    return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }

  function renderStatus() {
    const badge = document.getElementById('poiV70Status');
    const dot = document.getElementById('poiV70Dot');
    const elapsed = document.getElementById('poiV70Elapsed');
    const start = document.getElementById('poiV70Start');
    const mark = document.getElementById('poiV70Mark');
    const stop = document.getElementById('poiV70Stop');
    if (badge) badge.textContent = D.active ? `Sessão ativa · ${D.mode === 'full' ? 'completa' : 'rápida'}` : 'Nenhuma sessão ativa';
    if (dot) dot.className = `poi-v70-dot${D.active ? ' active' : ''}`;
    if (elapsed) elapsed.textContent = D.active ? elapsedLabel() : '—';
    if (start) start.disabled = D.active || D.stopping;
    if (mark) mark.disabled = !D.active || D.stopping;
    if (stop) stop.disabled = !D.active || D.stopping;
  }

  function renderPrevious(previous) {
    const root = document.getElementById('poiV70Previous');
    if (!root) return;
    if (!Array.isArray(previous) || !previous.length) {
      root.innerHTML = '<span class="muted">Nenhum diagnóstico anterior salvo.</span>';
      return;
    }
    root.innerHTML = `<strong>Sessões recentes</strong>${previous.map(item => `
      <div class="poi-v70-previous-row">
        <span><code>${q(item.session_id)}</code><br><small class="muted">${q(item.status || '—')} · ${q(item.started_at || '—')}</small></span>
        <a class="button ghost small" href="${q(item.export_url)}">Exportar ZIP</a>
      </div>`).join('')}`;
  }

  async function loadServerStatus() {
    try {
      const status = await apiJson('/api/diagnostics/session/status');
      if (status.active?.session_id && !D.active) {
        D.sessionId = status.active.session_id;
        D.mode = status.active.mode || 'full';
        D.active = true;
        D.startedAt = Date.parse(status.active.started_at || '') || Date.now();
        beginInstrumentation();
      }
      renderPrevious(status.previous || []);
      renderStatus();
    } catch (_) {}
  }

  function installPanel() {
    const view = document.getElementById('settingsView');
    if (!view || document.getElementById('poiV70Diagnostics')) return Boolean(document.getElementById('poiV70Diagnostics'));
    const section = document.createElement('section');
    section.id = 'poiV70Diagnostics';
    section.className = 'panel v58-panel poi-v70-diagnostics';
    section.innerHTML = `
      <div class="poi-v70-head">
        <div><p class="eyebrow">OBSERVABILIDADE · UX · PERFORMANCE</p><h2>Sessão de diagnóstico</h2><p class="muted paragraph">Grava uma sessão correlacionada do frontend, mídia, APIs, visão, ReID, Tonho, recorder e sistema. Use normalmente e marque o instante sempre que perceber algo estranho.</p></div>
        <div class="poi-v70-status"><span id="poiV70Dot" class="poi-v70-dot"></span><strong id="poiV70Status">Nenhuma sessão ativa</strong><span id="poiV70Elapsed" class="poi-v70-elapsed">—</span></div>
      </div>
      <div class="poi-v70-grid">
        <div class="poi-v70-card"><strong>Fluidez</strong><span class="muted">FPS da interface, long tasks, layout shifts, memória JS, waiting/stalled e frames perdidos do vídeo.</span></div>
        <div class="poi-v70-card"><strong>Funcionamento</strong><span class="muted">Ações → estado → API → componente, com tracks, ReID, Tonho, PTZ/visão e recorder correlacionados por horário.</span></div>
        <div class="poi-v70-card"><strong>Privacidade</strong><span class="muted">Sem embeddings brutos, credenciais RTSP, tokens Push/VAPID ou conteúdo de inputs. Texto do Tonho é opt-in.</span></div>
      </div>
      <div class="poi-v70-controls">
        <label>Nível<select id="poiV70Mode"><option value="full" selected>Completo · 5–15 min</option><option value="quick">Rápido · 2–3 min</option></select></label>
        <label class="poi-v70-check"><input id="poiV70Screen" type="checkbox"> Gravar tela junto (opcional)</label>
        <label class="poi-v70-check"><input id="poiV70TonhoText" type="checkbox"> Incluir texto das conversas do Tonho</label>
        <button type="button" class="button primary" id="poiV70Start">● Iniciar diagnóstico</button>
        <button type="button" class="button ghost poi-v70-marker" id="poiV70Mark" disabled>⚑ Marcar problema agora</button>
        <button type="button" class="button ghost" id="poiV70Stop" disabled>■ Encerrar e exportar ZIP</button>
      </div>
      <p class="muted poi-v70-note">Durante a sessão, reproduza os fluxos que quer validar: Live, Timeline (Anterior/Próxima/±10 s), Tonho, classificação manual, troca de câmeras, PTZ, gravação e demais ações. O botão ⚑ cria um ponto de referência exato para a análise.</p>
      <div id="poiV70Previous" class="poi-v70-previous"><span class="muted">Carregando sessões anteriores…</span></div>`;
    view.appendChild(section);
    document.getElementById('poiV70Start')?.addEventListener('click', startSession);
    document.getElementById('poiV70Mark')?.addEventListener('click', markProblem);
    document.getElementById('poiV70Stop')?.addEventListener('click', stopAndExport);
    loadServerStatus();
    return true;
  }

  patchFetch();
  installActionCapture();
  installErrorCapture();
  if (!installPanel()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (installPanel() || attempts > 80) clearInterval(timer);
    }, 200);
  }
})();
