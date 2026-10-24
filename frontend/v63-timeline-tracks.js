(() => {
  const T = {
    data: null,
    key: '',
    selectedEventId: null,
    overlayTimer: null,
    lastSecond: null,
    refreshTimer: null,
    wasActive: false,
    loading: false,
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

  function localDateString(date = new Date()) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  function clock(seconds) {
    const total = Math.max(0, Math.min(86400, Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function visibleEvents() {
    const events = T.data?.events || [];
    const showFp = Boolean(document.getElementById('poiTimelineShowFp')?.checked);
    return showFp ? events : events.filter(item => item.identity_state !== 'false_positive');
  }

  function isTimelineActive() {
    return Boolean(document.getElementById('timelineView')?.classList.contains('active'));
  }

  function isHybridPlaying() {
    const button = document.getElementById('poiHybridPlay');
    const video = document.getElementById('poiTimelineVideo');
    return Boolean(button?.textContent?.includes('❚') || (video && !video.hidden && !video.paused && !video.ended));
  }

  async function loadDay(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date || T.loading) return T.data;
    const key = `${cid}|${date}`;
    if (!force && T.data && T.key === key) return T.data;
    T.loading = true;
    const offset = -new Date().getTimezoneOffset();
    try {
      T.data = await api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`);
      T.key = key;
      renderTracks();
      return T.data;
    } catch (error) {
      if (typeof toast === 'function') toast(`Timeline: ${error.message}`, 'error');
      return T.data;
    } finally {
      T.loading = false;
    }
  }

  function installTracks() {
    const canvas = document.getElementById('poiTimelineCanvas');
    if (!canvas || document.getElementById('poiV63ContinuousTrack')) return Boolean(document.getElementById('poiV63ContinuousTrack'));
    const continuous = document.createElement('div');
    continuous.id = 'poiV63ContinuousTrack';
    continuous.className = 'poi-v63-track continuous';
    continuous.innerHTML = '<span class="poi-v63-track-label">Vídeo</span>';
    const clips = document.createElement('div');
    clips.id = 'poiV63ClipTrack';
    clips.className = 'poi-v63-track clips';
    clips.innerHTML = '<span class="poi-v63-track-label">Clipes</span>';
    const events = document.createElement('div');
    events.id = 'poiV63EventTrack';
    events.className = 'poi-v63-track events';
    events.innerHTML = '<span class="poi-v63-track-label">Eventos</span>';
    canvas.append(continuous, clips, events);
    return true;
  }

  function installOverlay() {
    const stage = document.getElementById('poiTimelineStage');
    if (!stage || document.getElementById('poiV63EventOverlay')) return;
    const overlay = document.createElement('div');
    overlay.id = 'poiV63EventOverlay';
    overlay.className = 'poi-v63-event-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <img id="poiV63OverlayImage" alt="Evento" hidden>
      <div class="meta"><b id="poiV63OverlayTime">--:--:--</b><strong id="poiV63OverlayLabel">Evento</strong><small id="poiV63OverlayDetail">Evento detectado</small></div>
      <div class="actions"><button type="button" class="button ghost small" id="poiV63OverlayClassify">Classificar</button><button type="button" class="button ghost small" id="poiV63OverlayClose">×</button></div>`;
    stage.appendChild(overlay);
    document.getElementById('poiV63OverlayClose')?.addEventListener('click', () => hideOverlay());
    document.getElementById('poiV63OverlayClassify')?.addEventListener('click', () => {
      const button = document.getElementById('poiTimelineClassify');
      if (T.selectedEventId && button) {
        button.dataset.eventId = String(T.selectedEventId);
        button.hidden = false;
        button.click();
      }
    });
  }

  function installPauseOption() {
    const meta = document.querySelector('.poi-hybrid-meta');
    if (!meta || document.getElementById('poiV63PauseEvents')) return;
    const label = document.createElement('label');
    label.className = 'poi-v63-pause-events';
    label.innerHTML = '<input id="poiV63PauseEvents" type="checkbox"><span>Pausar nos eventos</span>';
    meta.prepend(label);
  }

  function exactEventClipMap() {
    const map = new Map();
    for (const rec of T.data?.recordings || []) {
      if (rec.mode === 'event' && rec.source_event_id) map.set(Number(rec.source_event_id), rec);
    }
    return map;
  }

  function renderTracks() {
    if (!T.data || !installTracks()) return;
    const duration = Number(T.data.day_duration_seconds || 86400);
    const continuous = document.getElementById('poiV63ContinuousTrack');
    const clips = document.getElementById('poiV63ClipTrack');
    const eventsTrack = document.getElementById('poiV63EventTrack');
    if (!continuous || !clips || !eventsTrack) return;

    const recordings = T.data.recordings || [];
    const continuousRows = recordings.filter(rec => rec.mode === 'continuous');
    const clipRows = recordings.filter(rec => rec.mode === 'event');
    const clipMap = exactEventClipMap();
    const events = visibleEvents();

    continuous.innerHTML = '<span class="poi-v63-track-label">Vídeo</span>' + continuousRows.map(rec => {
      const left = (Number(rec.start_second || 0) / duration) * 100;
      const right = (Number(rec.end_second || 0) / duration) * 100;
      const width = Math.max(.06, right - left);
      return `<button type="button" class="poi-v63-range continuous ${rec.status === 'active' ? 'active' : ''}" data-v63-recording="${rec.id}" style="left:${left}%;width:${width}%" title="Vídeo contínuo ${clock(rec.start_second)}–${clock(rec.end_second)}"></button>`;
    }).join('');

    clips.innerHTML = '<span class="poi-v63-track-label">Clipes</span>' + clipRows.map(rec => {
      const left = (Number(rec.start_second || 0) / duration) * 100;
      const right = (Number(rec.end_second || 0) / duration) * 100;
      const width = Math.max(.08, right - left);
      const selected = T.selectedEventId && Number(rec.source_event_id) === Number(T.selectedEventId) ? ' selected' : '';
      return `<button type="button" class="poi-v63-range clip${selected}" data-v63-clip="${rec.id}" data-event-id="${rec.source_event_id || ''}" style="left:${left}%;width:${width}%" title="Clipe ${clock(rec.start_second)}–${clock(rec.end_second)}"></button>`;
    }).join('');

    const pointEvents = events.filter(event => !clipMap.has(Number(event.id)));
    eventsTrack.innerHTML = '<span class="poi-v63-track-label">Eventos</span>' + pointEvents.map(event => {
      const left = (Number(event.second || 0) / duration) * 100;
      const cls = event.identity_state === 'false_positive' ? ' fp' : event.person_id ? ' known' : '';
      const selected = Number(event.id) === Number(T.selectedEventId) ? ' selected' : '';
      return `<button type="button" class="poi-v63-event-point${cls}${selected}" data-event-id="${event.id}" style="left:${left}%" title="${q(event.label)} · ${clock(event.second)}"></button>`;
    }).join('');

    continuous.querySelectorAll('[data-v63-recording]').forEach(button => button.addEventListener('click', () => {
      const rec = recordings.find(item => Number(item.id) === Number(button.dataset.v63Recording));
      if (rec) seekSecond(Number(rec.start_second || 0) + .05);
    }));
    clips.querySelectorAll('[data-v63-clip]').forEach(button => button.addEventListener('click', () => {
      const rec = recordings.find(item => Number(item.id) === Number(button.dataset.v63Clip));
      if (!rec) return;
      const event = events.find(item => Number(item.id) === Number(rec.source_event_id));
      if (event) selectEvent(event, { seek: Number(rec.start_second || 0) + .05, persistent: !isHybridPlaying() });
      else seekSecond(Number(rec.start_second || 0) + .05);
    }));
    eventsTrack.querySelectorAll('[data-event-id]').forEach(button => button.addEventListener('click', () => {
      const event = events.find(item => Number(item.id) === Number(button.dataset.eventId));
      if (event) selectEvent(event, { persistent: !isHybridPlaying() });
    }));
  }

  function seekSecond(second) {
    const scrubber = document.getElementById('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || T.data?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function scrollThumb(eventId) {
    const strip = document.getElementById('poiEventStrip');
    const card = strip?.querySelector(`[data-event-card="${Number(eventId)}"]`);
    if (!strip || !card) return;
    strip.querySelectorAll('[data-event-card]').forEach(item => item.classList.toggle('selected', item === card));
    const target = card.offsetLeft - strip.clientWidth / 2 + card.offsetWidth / 2;
    strip.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
  }

  function syncSelection(eventId) {
    T.selectedEventId = Number(eventId || 0) || null;
    scrollThumb(T.selectedEventId);
    document.querySelectorAll('#poiV63EventTrack [data-event-id]').forEach(el => el.classList.toggle('selected', Number(el.dataset.eventId) === Number(T.selectedEventId)));
    document.querySelectorAll('#poiV63ClipTrack [data-event-id]').forEach(el => el.classList.toggle('selected', Number(el.dataset.eventId) === Number(T.selectedEventId)));
    const classify = document.getElementById('poiTimelineClassify');
    if (classify) {
      classify.hidden = !T.selectedEventId;
      if (T.selectedEventId) classify.dataset.eventId = String(T.selectedEventId);
    }
  }

  function selectEvent(event, { seek = null, persistent = true } = {}) {
    syncSelection(event.id);
    seekSecond(seek == null ? Number(event.second || 0) : seek);
    showOverlay(event, persistent);
  }

  function showOverlay(event, persistent = false) {
    installOverlay();
    const overlay = document.getElementById('poiV63EventOverlay');
    if (!overlay || !event) return;
    if (T.overlayTimer) clearTimeout(T.overlayTimer);
    T.selectedEventId = Number(event.id);
    syncSelection(event.id);
    const image = document.getElementById('poiV63OverlayImage');
    if (image) {
      image.hidden = !event.snapshot_url;
      if (event.snapshot_url) image.src = event.snapshot_url;
    }
    const time = document.getElementById('poiV63OverlayTime');
    const label = document.getElementById('poiV63OverlayLabel');
    const detail = document.getElementById('poiV63OverlayDetail');
    if (time) time.textContent = clock(event.second);
    if (label) label.textContent = event.label || `Evento #${event.id}`;
    if (detail) detail.textContent = event.recording_mode === 'continuous' ? 'Evento sobre gravação contínua' : event.recording_mode === 'event' ? 'Evento com clipe gravado' : 'Snapshot do evento';
    overlay.hidden = false;
    if (!persistent) T.overlayTimer = setTimeout(hideOverlay, 2600);
  }

  function hideOverlay() {
    const overlay = document.getElementById('poiV63EventOverlay');
    if (overlay) overlay.hidden = true;
    if (T.overlayTimer) clearTimeout(T.overlayTimer);
    T.overlayTimer = null;
  }

  function navigationItems() {
    if (!T.data) return [];
    const clips = exactEventClipMap();
    const events = visibleEvents();
    const items = events.map(event => {
      const clip = clips.get(Number(event.id));
      return clip
        ? { type: 'clip', anchor: Number(clip.start_second || 0), eventSecond: Number(event.second || 0), eventId: Number(event.id), recording: clip, event }
        : { type: 'event', anchor: Number(event.second || 0), eventSecond: Number(event.second || 0), eventId: Number(event.id), event };
    });
    const bound = new Set(items.filter(item => item.type === 'clip').map(item => Number(item.recording.id)));
    for (const rec of (T.data.recordings || []).filter(item => item.mode === 'event' && !bound.has(Number(item.id)))) {
      items.push({ type: 'clip', anchor: Number(rec.start_second || 0), eventSecond: Number(rec.start_second || 0), eventId: rec.source_event_id ? Number(rec.source_event_id) : null, recording: rec, event: null });
    }
    items.sort((a, b) => a.eventSecond - b.eventSecond || a.anchor - b.anchor);
    if (!items.length) {
      for (const rec of (T.data.recordings || []).filter(item => item.mode === 'continuous')) items.push({ type: 'continuous', anchor: Number(rec.start_second || 0), eventSecond: Number(rec.start_second || 0), eventId: null, recording: rec, event: null });
    }
    return items;
  }

  function jumpMedia(direction) {
    const items = navigationItems();
    if (!items.length) return;
    const current = Number(document.getElementById('poiDayScrubber')?.value || 0);
    const selectedIndex = T.selectedEventId ? items.findIndex(item => Number(item.eventId) === Number(T.selectedEventId)) : -1;
    let targetIndex = -1;
    if (selectedIndex >= 0) {
      targetIndex = selectedIndex + direction;
    } else if (direction > 0) {
      targetIndex = items.findIndex(item => item.eventSecond > current + .5);
    } else {
      for (let i = items.length - 1; i >= 0; i -= 1) {
        if (items[i].eventSecond < current - .5) { targetIndex = i; break; }
      }
    }
    if (targetIndex < 0 || targetIndex >= items.length) return;
    const item = items[targetIndex];
    if (item.event) syncSelection(item.event.id);
    if (item.type === 'clip') {
      seekSecond(item.anchor + .05);
      if (!isHybridPlaying() && item.event) showOverlay(item.event, true);
    } else if (item.event) {
      selectEvent(item.event, { persistent: !isHybridPlaying() });
    } else {
      seekSecond(item.anchor + .05);
    }
  }

  function bindNextPreviousOverride() {
    document.addEventListener('click', event => {
      const target = event.target.closest?.('#poiHybridNext,#poiHybridPrev');
      if (!target) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      loadDay(true).then(() => jumpMedia(target.id === 'poiHybridNext' ? 1 : -1));
    }, true);
  }

  function bindOriginalThumbSync() {
    document.addEventListener('click', event => {
      const card = event.target.closest?.('#poiEventStrip [data-event-card]');
      if (!card) return;
      const id = Number(card.dataset.eventCard || 0);
      if (!id) return;
      setTimeout(async () => {
        await loadDay(false);
        const item = visibleEvents().find(row => Number(row.id) === id);
        if (!item) return;
        syncSelection(id);
        if (!isHybridPlaying()) showOverlay(item, true);
      }, 0);
    });
  }

  function bindPlaybackEventOverlay() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video || video.dataset.poiV63Events === '1') return;
    video.dataset.poiV63Events = '1';
    video.addEventListener('timeupdate', () => {
      if (!T.data || video.hidden || video.paused) return;
      const now = Number(document.getElementById('poiDayScrubber')?.value || 0);
      const last = T.lastSecond;
      T.lastSecond = now;
      if (last == null || now < last || now - last > 5) return;
      const crossed = visibleEvents().filter(item => Number(item.second) > last && Number(item.second) <= now + .45);
      if (!crossed.length) return;
      const event = crossed[crossed.length - 1];
      const pause = Boolean(document.getElementById('poiV63PauseEvents')?.checked);
      showOverlay(event, pause);
      if (pause) {
        try { video.pause(); } catch (_) {}
        seekSecond(Number(event.second || now));
      }
    });
    video.addEventListener('seeking', () => { T.lastSecond = Number(document.getElementById('poiDayScrubber')?.value || 0); });
  }

  async function focusLatest() {
    const date = document.getElementById('poiTimelineDate');
    if (!date) return;
    const today = localDateString();
    if (date.value !== today) {
      date.value = today;
      date.dispatchEvent(new Event('change', { bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 260));
    }
    await loadDay(true);
    if (!T.data) return;
    if (T.data.is_today && T.data.recording?.mode === 'continuous' && T.data.now_second != null) {
      T.selectedEventId = null;
      hideOverlay();
      const nowButton = document.getElementById('poiTimelineNow');
      if (nowButton) nowButton.click();
      else seekSecond(Number(T.data.now_second));
      return;
    }
    const events = visibleEvents();
    if (events.length) {
      const last = events[events.length - 1];
      selectEvent(last, { persistent: true });
      return;
    }
    const recordings = T.data.recordings || [];
    if (recordings.length) seekSecond(Number(recordings[recordings.length - 1].end_second || recordings[recordings.length - 1].start_second || 0));
  }

  function bindTimelineEntry() {
    document.addEventListener('click', event => {
      if (!event.target.closest?.('[data-view="timeline"]')) return;
      setTimeout(focusLatest, 140);
    }, true);
    const view = document.getElementById('timelineView');
    if (!view) return;
    const observer = new MutationObserver(() => {
      const active = view.classList.contains('active');
      if (active && !T.wasActive) setTimeout(focusLatest, 80);
      T.wasActive = active;
    });
    T.wasActive = view.classList.contains('active');
    observer.observe(view, { attributes: true, attributeFilter: ['class'] });
  }

  async function showPersonPicker() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const picker = document.getElementById('poiClassifyPersonPicker');
    const actions = dialog?.querySelector('.poi-classify-actions');
    const cancel = document.getElementById('poiClassifyCancel');
    const select = document.getElementById('poiClassifyPersonSelect');
    if (!dialog || !picker || !select) return;
    picker.hidden = false;
    if (actions) actions.hidden = true;
    if (cancel) cancel.hidden = true;
    select.innerHTML = '<option value="">Carregando pessoas…</option>';
    let persons = [];
    try {
      const loaded = await api(`/api/persons?_=${Date.now()}`);
      if (Array.isArray(loaded)) persons = loaded;
    } catch (_) {}
    select.innerHTML = '<option value="">Selecione uma pessoa…</option>' + persons.map(person => `<option value="${Number(person.id)}">${q(person.name)}</option>`).join('') + '<option value="new">＋ Novo nome…</option>';
    const title = document.getElementById('poiClassifyTitle')?.textContent?.replace(/\?$/, '').trim().toLowerCase();
    const match = persons.find(person => String(person.name || '').trim().toLowerCase() === title);
    select.value = match ? String(match.id) : '';
    select.dispatchEvent(new Event('change'));
  }

  function bindPersonPickerOverride() {
    document.addEventListener('click', event => {
      const identify = event.target.closest?.('#poiClassifyIdentify');
      if (!identify) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      showPersonPicker();
    }, true);
  }

  function patchRecordingLabels() {
    document.querySelectorAll('[data-rec-event-field]').forEach(label => {
      for (const node of label.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
          if (node.textContent.trim() !== 'Duração do clipe de evento') node.textContent = 'Duração do clipe de evento';
          break;
        }
      }
      const small = label.querySelector('small');
      const help = 'Metade da duração fica antes do evento (pré-buffer) e metade depois. Eventos próximos estendem a janela.';
      if (small && small.textContent !== help) small.textContent = help;
    });
    document.querySelectorAll('.v58-camera-recording.collapsed .v58-mode-pill.event').forEach(pill => {
      const card = pill.closest('.v58-camera-recording');
      const headState = card?.querySelector('.v58-camera-recording-head>div>span');
      const summary = card?.querySelector('.v58-recording-summary>span');
      const stateText = 'Configurada · buffer pré-evento ativo';
      const summaryText = 'Pré-buffer contínuo · metade do clipe antes e metade depois do evento';
      if (headState && headState.textContent !== stateText) headState.textContent = stateText;
      if (summary && summary.textContent !== summaryText) summary.textContent = summaryText;
    });
  }

  function observeRecordingUi() {
    const root = document.getElementById('settingsView');
    if (!root) return;
    let scheduled = false;
    const run = () => { scheduled = false; patchRecordingLabels(); };
    new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(run);
    }).observe(root, { childList: true, subtree: true });
    patchRecordingLabels();
  }

  function bindReloads() {
    ['poiTimelineCamera', 'poiTimelineDate', 'poiTimelineShowFp'].forEach(id => document.getElementById(id)?.addEventListener('change', () => setTimeout(() => loadDay(true), 220)));
    document.getElementById('poiTimelineRefresh')?.addEventListener('click', () => setTimeout(() => loadDay(true), 160));
    T.refreshTimer = setInterval(() => { if (isTimelineActive()) loadDay(true); }, 12000);
  }

  async function init() {
    if (!document.getElementById('poiTimelinePlayer')) return false;
    installTracks();
    installOverlay();
    installPauseOption();
    bindNextPreviousOverride();
    bindOriginalThumbSync();
    bindPlaybackEventOverlay();
    bindTimelineEntry();
    bindPersonPickerOverride();
    bindReloads();
    observeRecordingUi();
    await loadDay(true);
    renderTracks();
    return true;
  }

  function wait() {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (document.getElementById('poiTimelinePlayer') && document.getElementById('poiHybridControls') && document.getElementById('poiClassifyPersonPicker')) {
        clearInterval(timer);
        init();
      } else if (attempts > 100) clearInterval(timer);
    }, 100);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wait, { once: true });
  else wait();
})();
