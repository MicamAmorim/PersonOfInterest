(() => {
  const V66 = {
    data: null,
    key: '',
    loading: false,
    lastSecond: null,
    selectedEventId: null,
    selectedAudioId: null,
    bboxTimer: null,
    audioTimer: null,
    dims: new Map(),
    observer: null,
    refreshTimer: null,
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function cameraId() {
    return Number(document.getElementById('poiTimelineCamera')?.value || 0) || null;
  }

  function dateValue() {
    return document.getElementById('poiTimelineDate')?.value || '';
  }

  function timelineActive() {
    return Boolean(document.getElementById('timelineView')?.classList.contains('active'));
  }

  function playing() {
    const video = document.getElementById('poiTimelineVideo');
    const button = document.getElementById('poiHybridPlay');
    return Boolean((video && !video.hidden && !video.paused && !video.ended) || button?.textContent?.includes('❚'));
  }

  function pauseOnEvents() {
    return Boolean(document.getElementById('poiV63PauseEvents')?.checked);
  }

  function clock(seconds) {
    const total = Math.max(0, Math.min(86400, Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  async function loadAnalysis(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date || V66.loading) return V66.data;
    const key = `${cid}|${date}`;
    if (!force && V66.data && V66.key === key) return V66.data;
    V66.loading = true;
    try {
      const offset = -new Date().getTimezoneOffset();
      V66.data = await api(`/api/timeline-player/analysis?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`);
      V66.key = key;
      renderAdditions();
      return V66.data;
    } catch (error) {
      if (typeof toast === 'function') toast(`Eventos/áudio: ${error.message}`, 'error');
      return V66.data;
    } finally {
      V66.loading = false;
    }
  }

  function events() {
    return Array.isArray(V66.data?.events) ? V66.data.events : [];
  }

  function audioSessions() {
    return Array.isArray(V66.data?.audio_sessions) ? V66.data.audio_sessions : [];
  }

  function eventById(id) {
    return events().find(item => Number(item.id) === Number(id)) || null;
  }

  function audioById(id) {
    return audioSessions().find(item => Number(item.id) === Number(id)) || null;
  }

  function installAudioTrack() {
    const canvas = document.getElementById('poiTimelineCanvas');
    if (!canvas) return null;
    let track = document.getElementById('poiV66AudioTrack');
    if (!track) {
      track = document.createElement('div');
      track.id = 'poiV66AudioTrack';
      track.className = 'poi-v63-track poi-v66-track-audio';
      track.innerHTML = '<span class="poi-v63-track-label">Tonho</span>';
      canvas.appendChild(track);
    }
    return track;
  }

  function installBBox() {
    const stage = document.getElementById('poiTimelineStage');
    if (!stage) return null;
    let box = document.getElementById('poiV66BBox');
    if (!box) {
      box = document.createElement('div');
      box.id = 'poiV66BBox';
      box.className = 'poi-v66-bbox';
      box.hidden = true;
      box.innerHTML = '<span id="poiV66BBoxLabel">Pessoa</span>';
      stage.appendChild(box);
    }
    return box;
  }

  function installAudioOverlay() {
    const stage = document.getElementById('poiTimelineStage');
    if (!stage) return null;
    let overlay = document.getElementById('poiV66AudioOverlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'poiV66AudioOverlay';
      overlay.className = 'poi-v66-audio-overlay';
      overlay.hidden = true;
      overlay.innerHTML = `
        <div class="poi-v66-audio-head"><div><strong>◉ TONHO</strong> <span id="poiV66AudioTime">--:--:--</span></div><button type="button" id="poiV66AudioClose" aria-label="Fechar">×</button></div>
        <div class="poi-v66-audio-turns" id="poiV66AudioTurns"></div>`;
      stage.appendChild(overlay);
      document.getElementById('poiV66AudioClose')?.addEventListener('click', () => hideAudioOverlay());
    }
    return overlay;
  }

  function seekSecond(second) {
    const scrubber = document.getElementById('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || V66.data?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function selectVisualEvent(event) {
    if (!event) return;
    V66.selectedEventId = Number(event.id);
    document.querySelectorAll('#poiV63EventTrack [data-event-id]').forEach(el => {
      el.classList.toggle('selected', Number(el.dataset.eventId) === Number(event.id));
    });
    document.querySelectorAll('#poiV63ClipTrack [data-event-id]').forEach(el => {
      el.classList.toggle('selected', Number(el.dataset.eventId) === Number(event.id));
    });
    const strip = document.getElementById('poiEventStrip');
    const card = strip?.querySelector(`[data-event-card="${Number(event.id)}"]`);
    if (strip && card) {
      strip.querySelectorAll('[data-event-card]').forEach(item => item.classList.toggle('selected', item === card));
      const left = card.offsetLeft - strip.clientWidth / 2 + card.offsetWidth / 2;
      strip.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
    }
    const classify = document.getElementById('poiTimelineClassify');
    if (classify) {
      classify.hidden = false;
      classify.dataset.eventId = String(event.id);
    }
  }

  function fillExistingEventCard(event, persistent = false) {
    const overlay = document.getElementById('poiV63EventOverlay');
    if (!overlay || !event) return;
    const image = document.getElementById('poiV63OverlayImage');
    const time = document.getElementById('poiV63OverlayTime');
    const label = document.getElementById('poiV63OverlayLabel');
    const detail = document.getElementById('poiV63OverlayDetail');
    if (image) {
      image.hidden = !event.snapshot_url;
      if (event.snapshot_url) image.src = event.snapshot_url;
    }
    if (time) time.textContent = clock(event.second);
    if (label) label.textContent = event.label || `Evento #${event.id}`;
    if (detail) detail.textContent = event.has_clip ? 'Evento com clipe gravado' : 'Evento visual';
    overlay.hidden = false;
    if (!persistent) {
      setTimeout(() => {
        if (!playing() && V66.selectedEventId === Number(event.id)) return;
        overlay.hidden = true;
      }, 2600);
    }
  }

  async function imageDimensions(url) {
    if (!url) return null;
    if (V66.dims.has(url)) return V66.dims.get(url);
    const dims = await new Promise(resolve => {
      const image = new Image();
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
      image.onerror = () => resolve(null);
      image.src = url;
    });
    V66.dims.set(url, dims);
    return dims;
  }

  function activeMediaElement() {
    const video = document.getElementById('poiTimelineVideo');
    if (video && !video.hidden) return video;
    const live = document.getElementById('poiTimelineLive');
    if (live && !live.hidden) return live;
    return null;
  }

  function hideBBox() {
    const box = document.getElementById('poiV66BBox');
    if (box) box.hidden = true;
    if (V66.bboxTimer) clearTimeout(V66.bboxTimer);
    V66.bboxTimer = null;
  }

  async function showBBox(event, persistent = false) {
    const box = installBBox();
    const media = activeMediaElement();
    if (!box || !media || !event?.bbox || !event?.snapshot_url) {
      hideBBox();
      return;
    }
    const dims = await imageDimensions(event.snapshot_url);
    if (!dims?.width || !dims?.height) {
      hideBBox();
      return;
    }
    const stage = document.getElementById('poiTimelineStage');
    if (!stage) return;
    const stageRect = stage.getBoundingClientRect();
    const mediaRect = media.getBoundingClientRect();
    if (!mediaRect.width || !mediaRect.height) return;

    let aspect = dims.width / dims.height;
    const video = media.tagName === 'VIDEO' ? media : null;
    if (video?.videoWidth && video?.videoHeight) aspect = video.videoWidth / video.videoHeight;
    const containerAspect = mediaRect.width / mediaRect.height;
    let contentWidth = mediaRect.width;
    let contentHeight = mediaRect.height;
    let offsetX = 0;
    let offsetY = 0;
    if (containerAspect > aspect) {
      contentWidth = contentHeight * aspect;
      offsetX = (mediaRect.width - contentWidth) / 2;
    } else {
      contentHeight = contentWidth / aspect;
      offsetY = (mediaRect.height - contentHeight) / 2;
    }

    const b = event.bbox;
    const left = mediaRect.left - stageRect.left + offsetX + (Number(b.x) / dims.width) * contentWidth;
    const top = mediaRect.top - stageRect.top + offsetY + (Number(b.y) / dims.height) * contentHeight;
    const width = (Number(b.w) / dims.width) * contentWidth;
    const height = (Number(b.h) / dims.height) * contentHeight;
    if (![left, top, width, height].every(Number.isFinite) || width < 2 || height < 2) {
      hideBBox();
      return;
    }
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
    box.style.width = `${width}px`;
    box.style.height = `${height}px`;
    const label = document.getElementById('poiV66BBoxLabel');
    if (label) label.textContent = event.label || 'Pessoa';
    box.hidden = false;
    if (V66.bboxTimer) clearTimeout(V66.bboxTimer);
    if (!persistent) V66.bboxTimer = setTimeout(hideBBox, 2800);
  }

  function showAudioOverlay(session, persistent = false) {
    const overlay = installAudioOverlay();
    if (!overlay || !session) return;
    if (V66.audioTimer) clearTimeout(V66.audioTimer);
    V66.selectedAudioId = Number(session.id);
    document.querySelectorAll('#poiV66AudioTrack [data-audio-id]').forEach(el => {
      el.classList.toggle('selected', Number(el.dataset.audioId) === Number(session.id));
    });
    const time = document.getElementById('poiV66AudioTime');
    const turns = document.getElementById('poiV66AudioTurns');
    if (time) time.textContent = clock(session.start_second);
    if (turns) {
      turns.innerHTML = (session.turns || []).map(turn => `
        <div class="poi-v66-audio-turn">
          <b>Você</b><p>${q(turn.user || '—')}</p>
          <b class="tonho">Tonho</b><p>${q(turn.tonho || '—')}</p>
        </div>`).join('') || '<div class="poi-v66-audio-turn"><p>Wake do Tonho detectado.</p></div>';
    }
    overlay.hidden = false;
    if (!persistent) V66.audioTimer = setTimeout(hideAudioOverlay, 5200);
  }

  function hideAudioOverlay() {
    const overlay = document.getElementById('poiV66AudioOverlay');
    if (overlay) overlay.hidden = true;
    if (V66.audioTimer) clearTimeout(V66.audioTimer);
    V66.audioTimer = null;
  }

  function focusVisualEvent(event) {
    if (!event) return;
    selectVisualEvent(event);
    seekSecond(Number(event.second || 0));
    fillExistingEventCard(event, true);
    setTimeout(() => showBBox(event, true), 120);
  }

  function focusAudioSession(session) {
    if (!session) return;
    seekSecond(Number(session.start_second || 0));
    showAudioOverlay(session, !playing());
  }

  function renderClipEventPoints() {
    const track = document.getElementById('poiV63EventTrack');
    if (!track || !V66.data) return;
    const duration = Number(V66.data.day_duration_seconds || 86400);
    for (const event of events().filter(item => item.has_clip)) {
      if (track.querySelector(`[data-v66-event-id="${Number(event.id)}"]`)) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `poi-v63-event-point poi-v66-event-with-clip${event.identity_state === 'false_positive' ? ' fp' : ''}`;
      button.dataset.v66EventId = String(event.id);
      button.dataset.eventId = String(event.id);
      button.style.left = `${(Number(event.second || 0) / duration) * 100}%`;
      button.title = `${event.label || 'Evento'} · ${clock(event.second)} · evento do clipe`;
      button.addEventListener('click', click => {
        click.stopPropagation();
        focusVisualEvent(event);
      });
      track.appendChild(button);
    }
  }

  function renderAudioTrack() {
    const track = installAudioTrack();
    if (!track || !V66.data) return;
    const duration = Number(V66.data.day_duration_seconds || 86400);
    track.querySelectorAll('[data-audio-id]').forEach(node => node.remove());
    for (const session of audioSessions()) {
      const left = (Number(session.start_second || 0) / duration) * 100;
      const end = Math.max(Number(session.end_second || session.start_second || 0), Number(session.start_second || 0) + 4);
      const width = Math.max(.12, ((end - Number(session.start_second || 0)) / duration) * 100);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'poi-v66-audio-range';
      button.dataset.audioId = String(session.id);
      button.style.left = `${left}%`;
      button.style.width = `${width}%`;
      const preview = session.turns?.[0]?.user || 'Wake do Tonho';
      button.title = `Tonho ${clock(session.start_second)} · ${preview}`;
      button.addEventListener('click', event => {
        event.stopPropagation();
        focusAudioSession(session);
      });
      track.appendChild(button);
    }
  }

  function renderAdditions() {
    installAudioTrack();
    installBBox();
    installAudioOverlay();
    renderClipEventPoints();
    renderAudioTrack();
    const pause = document.getElementById('poiV63PauseEvents');
    if (pause) pause.title = 'Pausa em eventos visuais e conversas iniciadas por wake do Tonho.';
  }

  function bindClassificationCard() {
    const classify = document.getElementById('poiV63OverlayClassify');
    if (!classify || classify.dataset.poiV66Bound === '1') return;
    classify.dataset.poiV66Bound = '1';
    classify.addEventListener('click', event => {
      if (!V66.selectedEventId) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const button = document.getElementById('poiTimelineClassify');
      if (!button) return;
      button.dataset.eventId = String(V66.selectedEventId);
      button.hidden = false;
      button.click();
    }, true);
    document.getElementById('poiV63OverlayClose')?.addEventListener('click', () => hideBBox());
  }

  function bindClicks() {
    document.addEventListener('click', event => {
      const clip = event.target.closest?.('#poiV63ClipTrack [data-event-id]');
      const point = event.target.closest?.('#poiV63EventTrack [data-event-id]');
      const card = event.target.closest?.('#poiEventStrip [data-event-card]');
      const id = Number(clip?.dataset.eventId || point?.dataset.eventId || card?.dataset.eventCard || 0);
      if (!id) return;
      const item = eventById(id);
      if (!item) return;
      V66.selectedEventId = id;
      setTimeout(() => showBBox(item, !playing()), 150);
    }, true);
  }

  function bindVideoCrossings() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video || video.dataset.poiV66Bound === '1') return;
    video.dataset.poiV66Bound = '1';
    video.addEventListener('timeupdate', () => {
      if (!V66.data || video.hidden || video.paused) return;
      const now = Number(document.getElementById('poiDayScrubber')?.value || 0);
      const last = V66.lastSecond;
      V66.lastSecond = now;
      if (last == null || now < last || now - last > 5) return;

      const crossedVisual = events().filter(item => Number(item.second) > last && Number(item.second) <= now + .45);
      if (crossedVisual.length) {
        const item = crossedVisual[crossedVisual.length - 1];
        V66.selectedEventId = Number(item.id);
        showBBox(item, pauseOnEvents());
      }

      const crossedAudio = audioSessions().filter(item => Number(item.start_second) > last && Number(item.start_second) <= now + .45);
      if (crossedAudio.length) {
        const session = crossedAudio[crossedAudio.length - 1];
        const pause = pauseOnEvents();
        showAudioOverlay(session, pause);
        if (pause) {
          try { video.pause(); } catch (_) {}
          seekSecond(Number(session.start_second || now));
        }
      }
    });
    video.addEventListener('seeking', () => {
      V66.lastSecond = Number(document.getElementById('poiDayScrubber')?.value || 0);
    });
    video.addEventListener('play', () => {
      const box = document.getElementById('poiV66BBox');
      if (box && !box.hidden) {
        if (V66.bboxTimer) clearTimeout(V66.bboxTimer);
        V66.bboxTimer = setTimeout(hideBBox, 2800);
      }
      const audio = document.getElementById('poiV66AudioOverlay');
      if (audio && !audio.hidden) {
        if (V66.audioTimer) clearTimeout(V66.audioTimer);
        V66.audioTimer = setTimeout(hideAudioOverlay, 5200);
      }
    });
  }

  function observeV63Renders() {
    const track = document.getElementById('poiV63EventTrack');
    if (!track || V66.observer) return;
    V66.observer = new MutationObserver(() => {
      requestAnimationFrame(() => {
        renderClipEventPoints();
        bindClassificationCard();
      });
    });
    V66.observer.observe(track, { childList: true });
  }

  function bindRefreshes() {
    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => {
      document.getElementById(id)?.addEventListener('change', () => {
        V66.data = null;
        V66.key = '';
        V66.lastSecond = null;
        hideBBox();
        hideAudioOverlay();
        setTimeout(() => loadAnalysis(true), 320);
      });
    });
    document.getElementById('poiTimelineRefresh')?.addEventListener('click', () => setTimeout(() => loadAnalysis(true), 220));
    if (!V66.refreshTimer) {
      V66.refreshTimer = setInterval(() => {
        if (timelineActive()) loadAnalysis(true);
      }, 15000);
    }
  }

  function init() {
    if (!document.getElementById('poiTimelinePlayer') || !document.getElementById('poiV63EventTrack')) return false;
    renderAdditions();
    bindClassificationCard();
    bindClicks();
    bindVideoCrossings();
    observeV63Renders();
    bindRefreshes();
    loadAnalysis(true);
    window.addEventListener('resize', () => {
      if (!V66.selectedEventId) return;
      const item = eventById(V66.selectedEventId);
      const box = document.getElementById('poiV66BBox');
      if (item && box && !box.hidden) showBBox(item, true);
    });
    return true;
  }

  function wait() {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (init() || attempts > 120) clearInterval(timer);
    }, 100);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wait, { once: true });
  else wait();
})();
