(() => {
  const S = {
    day: null,
    analysis: null,
    key: '',
    loading: null,
    observer: null,
    applyScheduled: false,
    navToken: 0,
    currentKey: null,
  };

  const el = id => document.getElementById(id);
  const core = () => window.poiTimelineCore || null;

  function cameraId() { return Number(el('poiTimelineCamera')?.value || 0) || null; }
  function dateValue() { return el('poiTimelineDate')?.value || ''; }
  function timelineActive() { return Boolean(el('timelineView')?.classList.contains('active')); }
  function showFalsePositives() { return Boolean(el('poiTimelineShowFp')?.checked); }

  function isFalsePositiveEvent(item) {
    const state = String(item?.identity_state || '').trim().toLowerCase();
    const label = String(item?.label || '').trim().toLowerCase();
    return state === 'false_positive' || label === 'falso positivo';
  }

  function falsePositiveIds() {
    return new Set((S.day?.events || []).filter(isFalsePositiveEvent).map(item => Number(item.id)).filter(Number.isFinite));
  }

  function visibleEvents() {
    const fromCore = core()?.getVisibleEvents?.();
    if (Array.isArray(fromCore)) return fromCore;
    const events = S.day?.events || [];
    return showFalsePositives() ? events : events.filter(item => !isFalsePositiveEvent(item));
  }

  function visibleRecordings() {
    const fromCore = core()?.getVisibleRecordings?.();
    if (Array.isArray(fromCore)) return fromCore;
    const recs = S.day?.recordings || [];
    if (showFalsePositives()) return recs;
    const fp = falsePositiveIds();
    return recs.filter(rec => String(rec.mode || '') !== 'event' || !rec.source_event_id || !fp.has(Number(rec.source_event_id)));
  }

  async function loadData(force = false) {
    const cid = cameraId(), date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && S.day && S.analysis && S.key === key) return { day: S.day, analysis: S.analysis };
    if (S.loading && S.key === key) return S.loading;
    S.key = key;
    const offset = -new Date().getTimezoneOffset();
    S.loading = Promise.all([
      api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
      api(`/api/timeline-player/analysis?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
    ]).then(([day, analysis]) => { S.day = day; S.analysis = analysis; return { day, analysis }; })
      .catch(() => ({ day: S.day, analysis: S.analysis }))
      .finally(() => { S.loading = null; });
    return S.loading;
  }

  function recordingById(id) {
    return (S.day?.recordings || []).find(item => Number(item.id) === Number(id)) || null;
  }

  function setFiltered(node, filtered) {
    if (!node) return;
    if (filtered) {
      node.dataset.poiFpFiltered = '1';
      node.hidden = true;
      node.style.display = 'none';
      node.classList.remove('selected');
      return;
    }
    if (node.dataset.poiFpFiltered !== '1') return;
    delete node.dataset.poiFpFiltered;
    node.hidden = false;
    node.style.removeProperty('display');
  }

  function applyFilter() {
    S.applyScheduled = false;
    if (!S.day) return;
    const fp = falsePositiveIds();
    const filtering = !showFalsePositives();

    document.querySelectorAll('#poiTimelinePlayer [data-event-id]').forEach(node => {
      const id = Number(node.dataset.eventId || 0);
      setFiltered(node, filtering && id > 0 && fp.has(id));
    });
    document.querySelectorAll('#poiEventStrip [data-event-card]').forEach(node => {
      const id = Number(node.dataset.eventCard || 0);
      setFiltered(node, filtering && id > 0 && fp.has(id));
    });
    document.querySelectorAll('#poiCoverageTrack [data-recording-id], #poiV63ClipTrack [data-v63-clip]').forEach(node => {
      const recId = Number(node.dataset.recordingId || node.dataset.v63Clip || 0);
      const rec = recordingById(recId);
      const hide = filtering && rec && String(rec.mode || '') === 'event' && rec.source_event_id && fp.has(Number(rec.source_event_id));
      setFiltered(node, Boolean(hide));
    });

    if (!filtering) return;
    const selectedId = Number(el('poiTimelineClassify')?.dataset.eventId || 0);
    const overlaySaysFp = String(el('poiV63OverlayLabel')?.textContent || '').trim().toLowerCase() === 'falso positivo';
    if ((selectedId && fp.has(selectedId)) || overlaySaysFp) {
      const overlay = el('poiV63EventOverlay'); if (overlay) overlay.hidden = true;
      const bbox = el('poiV66BBox'); if (bbox) bbox.hidden = true;
      const classify = el('poiTimelineClassify'); if (classify) { classify.hidden = true; delete classify.dataset.eventId; }
    }
    const video = el('poiTimelineVideo');
    const active = video && !video.hidden ? recordingById(video.dataset.recordingId) : null;
    if (active && String(active.mode || '') === 'event' && active.source_event_id && fp.has(Number(active.source_event_id))) {
      try { video.pause(); } catch (_) {}
      video.hidden = true;
      S.currentKey = null;
    }
  }

  function scheduleApplyFilter() {
    if (S.applyScheduled) return;
    S.applyScheduled = true;
    requestAnimationFrame(applyFilter);
  }

  function itemKey(item) {
    if (item?.rec) return `rec:${Number(item.rec.id)}`;
    if (item?.event) return `event:${Number(item.event.id)}`;
    if (item?.session) return `audio:${Number(item.session.id)}`;
    return '';
  }

  function mediaItems() {
    const recordings = visibleRecordings()
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .map(rec => ({ type: 'recording', start: Number(rec.start_second || 0), end: Number(rec.end_second || 0), rec }));

    const recordingIds = new Set(recordings.map(item => Number(item.rec.id)));
    const snapshots = visibleEvents()
      .filter(event => event.snapshot_url)
      .filter(event => !event.recording_id || !recordingIds.has(Number(event.recording_id)))
      .map(event => ({ type: 'snapshot', start: Number(event.second || 0), end: Number(event.second || 0), event }));

    const audio = (S.analysis?.audio_sessions || []).map(session => ({
      type: 'audio', start: Number(session.start_second || 0),
      end: Math.max(Number(session.end_second || session.start_second || 0), Number(session.start_second || 0) + 4), session,
    }));

    const rank = { recording: 0, snapshot: 1, audio: 2 };
    return [...recordings, ...snapshots, ...audio].sort((a, b) => {
      const dt = Number(a.start) - Number(b.start);
      if (Math.abs(dt) > .0001) return dt;
      const dr = rank[a.type] - rank[b.type];
      return dr || itemKey(a).localeCompare(itemKey(b));
    });
  }

  function currentSecond() {
    return Number(el('poiDayScrubber')?.value || core()?.getCurrentSecond?.() || 0);
  }

  function currentMediaKey(items) {
    const video = el('poiTimelineVideo');
    if (video && !video.hidden && Number(video.dataset.recordingId || 0)) {
      const key = `rec:${Number(video.dataset.recordingId)}`;
      if (items.some(item => itemKey(item) === key)) return key;
    }

    const selectedAudio = document.querySelector('#poiV66AudioTrack [data-audio-id].selected');
    const audioOverlay = el('poiV66AudioOverlay');
    if (selectedAudio && audioOverlay && !audioOverlay.hidden) {
      const key = `audio:${Number(selectedAudio.dataset.audioId)}`;
      if (items.some(item => itemKey(item) === key)) return key;
    }

    const snapshot = el('poiTimelineSnapshot');
    if (snapshot && !snapshot.hidden) {
      const selected = document.querySelector('#poiEventStrip [data-event-card].selected, #poiEventMarkers [data-event-id].selected');
      const id = Number(selected?.dataset.eventCard || selected?.dataset.eventId || 0);
      const key = id ? `event:${id}` : '';
      if (key && items.some(item => itemKey(item) === key)) return key;
    }

    if (S.currentKey && items.some(item => itemKey(item) === S.currentKey)) return S.currentKey;
    return null;
  }

  function neighborByIndex(items, direction) {
    if (!items.length) return null;
    const key = currentMediaKey(items);
    if (key) {
      const index = items.findIndex(item => itemKey(item) === key);
      if (index >= 0) return items[index + direction] || null;
    }

    const now = currentSecond();
    if (direction > 0) return items.find(item => Number(item.start) > now + .001) || null;
    for (let index = items.length - 1; index >= 0; index -= 1) {
      if (Number(items[index].start) < now - .001) return items[index];
    }
    return null;
  }

  function videoActuallyPlaying() {
    const video = el('poiTimelineVideo');
    return Boolean(video && !video.hidden && !video.paused && !video.ended);
  }

  function syncNeedleOnly(second) {
    const scrubber = el('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || S.day?.day_duration_seconds || 86400);
    const value = Math.max(0, Math.min(max, Number(second) || 0));
    scrubber.step = '0.01';
    scrubber.value = String(value);
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
  }

  async function focusMediaItem(item, resume) {
    if (!item) return false;
    const key = itemKey(item);
    const timelineCore = core();

    if (item.type === 'recording' && timelineCore?.selectRecordingById) {
      S.currentKey = key;
      const ok = await timelineCore.selectRecordingById(Number(item.rec.id), { autoplay: Boolean(resume), scroll: true, offsetSeconds: .02 });
      if (!ok) S.currentKey = null;
      return Boolean(ok);
    }

    if (item.type === 'snapshot' && timelineCore?.selectEventById) {
      S.currentKey = key;
      const ok = await timelineCore.selectEventById(Number(item.event.id), { autoplay: false, scroll: true });
      if (!ok) S.currentKey = null;
      return Boolean(ok);
    }

    if (item.type === 'audio') {
      const button = document.querySelector(`#poiV66AudioTrack [data-audio-id="${Number(item.session.id)}"]`);
      if (!button) return false;
      S.currentKey = key;
      button.click();
      syncNeedleOnly(Number(item.start));
      return true;
    }

    return false;
  }

  async function jumpMedia(direction) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken || !S.day) return;
    const items = mediaItems();
    const target = neighborByIndex(items, direction);
    if (!target) return;
    const resume = videoActuallyPlaying();
    await focusMediaItem(target, resume);
  }

  function bindNavigationOwner() {
    if (window.__poiV73NavigationBound) return;
    window.__poiV73NavigationBound = true;
    window.__poiTimelineNavigationOwner = 'v73';
    window.addEventListener('click', event => {
      if (!timelineActive()) return;
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
      if (!next && !previous) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void jumpMedia(next ? 1 : -1);
    }, true);
  }

  function observeRenders() {
    if (S.observer) return;
    const root = el('poiTimelinePlayer');
    if (!root) return;
    S.observer = new MutationObserver(scheduleApplyFilter);
    S.observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'class', 'style', 'data-event-id', 'data-event-card', 'data-recording-id', 'data-v63-clip'] });
  }

  function invalidate() {
    S.day = null; S.analysis = null; S.key = ''; S.currentKey = null; S.navToken += 1;
  }

  function bindStateSync() {
    document.addEventListener('poi:timeline-media-selected', event => {
      const detail = event.detail || {};
      if (detail.type === 'recording' && detail.recordingId) S.currentKey = `rec:${Number(detail.recordingId)}`;
      else if (detail.type === 'event' && detail.eventId) S.currentKey = `event:${Number(detail.eventId)}`;
      else S.currentKey = null;
    });

    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => el(id)?.addEventListener('change', () => { invalidate(); setTimeout(() => loadData(true).then(scheduleApplyFilter), 250); }));
    el('poiTimelineRefresh')?.addEventListener('click', () => { invalidate(); setTimeout(() => loadData(true).then(scheduleApplyFilter), 220); });
    el('poiTimelineShowFp')?.addEventListener('change', () => { S.currentKey = null; scheduleApplyFilter(); setTimeout(scheduleApplyFilter, 80); });
    el('poiDayScrubber')?.addEventListener('input', event => { if (event.isTrusted) S.currentKey = null; });

    document.addEventListener('click', event => {
      if (!event.isTrusted || !timelineActive()) return;
      if (event.target.closest?.('#poiEventStrip [data-event-card], #poiEventMarkers [data-event-id], #poiCoverageTrack [data-recording-id], #poiV63EventTrack [data-event-id], #poiV63ClipTrack [data-event-id], #poiV66AudioTrack [data-audio-id]')) S.currentKey = null;
    }, true);
  }

  function init() {
    if (!el('poiTimelinePlayer')) return false;
    if (el('poiDayScrubber')) el('poiDayScrubber').step = '0.01';
    bindNavigationOwner();
    bindStateSync();
    observeRenders();
    void loadData(true).then(scheduleApplyFilter);
    return true;
  }

  bindNavigationOwner();
  if (!init()) {
    let attempts = 0;
    const timer = setInterval(() => { attempts += 1; if (init() || attempts > 120) clearInterval(timer); }, 100);
  }
})();