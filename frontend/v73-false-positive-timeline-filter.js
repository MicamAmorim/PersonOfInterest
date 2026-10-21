(() => {
  const S = {
    day: null,
    analysis: null,
    key: '',
    loading: null,
    observer: null,
    applyScheduled: false,
    lastSecond: null,
    suppressFpUntil: 0,
    navToken: 0,
    navKey: null,
  };

  const el = id => document.getElementById(id);

  function cameraId() {
    return Number(el('poiTimelineCamera')?.value || 0) || null;
  }

  function dateValue() {
    return el('poiTimelineDate')?.value || '';
  }

  function timelineActive() {
    return Boolean(el('timelineView')?.classList.contains('active'));
  }

  function showFalsePositives() {
    return Boolean(el('poiTimelineShowFp')?.checked);
  }

  function hybridPlaying() {
    const play = el('poiHybridPlay');
    const video = el('poiTimelineVideo');
    return Boolean(play?.textContent?.includes('❚') || (video && !video.hidden && !video.paused && !video.ended));
  }

  function isFalsePositiveEvent(item) {
    const state = String(item?.identity_state || '').trim().toLowerCase();
    const label = String(item?.label || '').trim().toLowerCase();
    return state === 'false_positive' || label === 'falso positivo';
  }

  function falsePositiveIds() {
    return new Set((S.day?.events || [])
      .filter(isFalsePositiveEvent)
      .map(item => Number(item.id))
      .filter(Number.isFinite));
  }

  function recordingById(id) {
    return (S.day?.recordings || []).find(item => Number(item.id) === Number(id)) || null;
  }

  function isHiddenFalsePositiveRecording(rec, ids = falsePositiveIds()) {
    if (!rec || showFalsePositives()) return false;
    return String(rec.mode || '') === 'event'
      && Number(rec.source_event_id || 0) > 0
      && ids.has(Number(rec.source_event_id));
  }

  async function loadData(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && S.day && S.analysis && S.key === key) return { day: S.day, analysis: S.analysis };
    if (S.loading && S.key === key) return S.loading;
    S.key = key;
    const offset = -new Date().getTimezoneOffset();
    S.loading = Promise.all([
      api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
      api(`/api/timeline-player/analysis?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
    ]).then(([day, analysis]) => {
      S.day = day;
      S.analysis = analysis;
      return { day, analysis };
    }).catch(() => ({ day: S.day, analysis: S.analysis }))
      .finally(() => { S.loading = null; });
    return S.loading;
  }

  function setFiltered(node, filtered) {
    if (!node) return;
    const shouldHide = Boolean(filtered);
    if (shouldHide) {
      if (node.dataset.poiFpFiltered !== '1') node.dataset.poiFpFiltered = '1';
      if (!node.hidden) node.hidden = true;
      if (node.style.display !== 'none') node.style.display = 'none';
      if (node.classList.contains('selected')) node.classList.remove('selected');
      return;
    }
    if (node.dataset.poiFpFiltered !== '1') return;
    delete node.dataset.poiFpFiltered;
    if (node.style.display === 'none') node.style.removeProperty('display');
    if (node.hidden) node.hidden = false;
  }

  function selectedEventId() {
    const classify = Number(el('poiTimelineClassify')?.dataset.eventId || 0);
    if (classify) return classify;
    const node = document.querySelector([
      '#poiV63ClipTrack [data-event-id].selected',
      '#poiV63EventTrack [data-event-id].selected',
      '#poiEventMarkers [data-event-id].selected',
      '#poiEventStrip [data-event-card].selected',
    ].join(','));
    return Number(node?.dataset.eventId || node?.dataset.eventCard || 0) || null;
  }

  function hideVisualEventArtifacts() {
    const overlay = el('poiV63EventOverlay');
    const bbox = el('poiV66BBox');
    const classify = el('poiTimelineClassify');
    if (overlay && !overlay.hidden) overlay.hidden = true;
    if (bbox && !bbox.hidden) bbox.hidden = true;
    if (classify) {
      classify.hidden = true;
      delete classify.dataset.eventId;
    }
  }

  function clearHiddenCurrentRecording(ids) {
    const video = el('poiTimelineVideo');
    if (!video || video.hidden) return;
    const rec = recordingById(video.dataset.recordingId);
    if (!isHiddenFalsePositiveRecording(rec, ids)) return;
    try { video.pause(); } catch (_) {}
    video.hidden = true;
    const snapshot = el('poiTimelineSnapshot');
    if (snapshot) snapshot.hidden = true;
    const empty = el('poiTimelineEmpty');
    if (empty) empty.hidden = false;
    const title = el('poiMediaTitle');
    if (title) title.textContent = 'Sem mídia visível neste horário';
    S.navKey = null;
  }

  function applyFilter() {
    S.applyScheduled = false;
    if (!S.day) return;
    const ids = falsePositiveIds();
    const filtering = !showFalsePositives();

    document.querySelectorAll('#poiTimelinePlayer [data-event-id]').forEach(node => {
      const id = Number(node.dataset.eventId || 0);
      setFiltered(node, filtering && id > 0 && ids.has(id));
    });
    document.querySelectorAll('#poiEventStrip [data-event-card]').forEach(node => {
      const id = Number(node.dataset.eventCard || 0);
      setFiltered(node, filtering && id > 0 && ids.has(id));
    });
    document.querySelectorAll('#poiCoverageTrack [data-recording-id]').forEach(node => {
      const rec = recordingById(node.dataset.recordingId);
      setFiltered(node, filtering && isHiddenFalsePositiveRecording(rec, ids));
    });

    if (!filtering) return;

    const selected = selectedEventId();
    const overlaySaysFp = String(el('poiV63OverlayLabel')?.textContent || '').trim().toLowerCase() === 'falso positivo';
    if ((selected && ids.has(selected)) || overlaySaysFp || performance.now() < S.suppressFpUntil) {
      hideVisualEventArtifacts();
    }
    clearHiddenCurrentRecording(ids);
  }

  function scheduleApplyFilter() {
    if (S.applyScheduled) return;
    S.applyScheduled = true;
    requestAnimationFrame(applyFilter);
  }

  function playbackSecond() {
    const video = el('poiTimelineVideo');
    if (video && !video.hidden) {
      const rec = recordingById(video.dataset.recordingId);
      if (rec) return Number(rec.start_second || 0) + Number(video.currentTime || 0);
    }
    return Number(el('poiDayScrubber')?.value || 0);
  }

  function latestCrossedEvent(last, now) {
    if (!S.day || last == null || now < last || now - last > 5) return null;
    const crossed = (S.day.events || [])
      .filter(item => Number(item.second) > last && Number(item.second) <= now + .45)
      .sort((a, b) => Number(a.second) - Number(b.second));
    return crossed.length ? crossed[crossed.length - 1] : null;
  }

  function syncPreciseScrubber(second) {
    const scrubber = el('poiDayScrubber');
    if (!scrubber || document.activeElement === scrubber) return;
    scrubber.step = '0.01';
    const max = Number(scrubber.max || S.day?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Number(second) || 0)));
  }

  function bindVideoGuard() {
    const video = el('poiTimelineVideo');
    if (!video || video.dataset.poiV73FpBound === '1') return;
    video.dataset.poiV73FpBound = '1';
    video.addEventListener('timeupdate', () => {
      const now = playbackSecond();
      syncPreciseScrubber(now);
      const latest = latestCrossedEvent(S.lastSecond, now);
      S.lastSecond = now;
      if (!showFalsePositives() && latest && isFalsePositiveEvent(latest)) {
        S.suppressFpUntil = performance.now() + 400;
        queueMicrotask(() => {
          hideVisualEventArtifacts();
          scheduleApplyFilter();
        });
      }
    });
    video.addEventListener('seeking', () => { S.lastSecond = playbackSecond(); });
  }

  function itemKey(item) {
    if (item?.rec) return `rec:${Number(item.rec.id)}`;
    if (item?.event) return `event:${Number(item.event.id)}`;
    if (item?.session) return `audio:${Number(item.session.id)}`;
    return '';
  }

  function itemEventId(item) {
    return Number(item?.event?.id || item?.rec?.source_event_id || 0) || null;
  }

  function mediaItems(includeFalsePositives) {
    const ids = falsePositiveIds();
    const recordings = (S.day?.recordings || [])
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .filter(rec => includeFalsePositives || String(rec.mode || '') !== 'event' || !rec.source_event_id || !ids.has(Number(rec.source_event_id)))
      .map(rec => ({
        type: 'recording',
        start: Number(rec.start_second || 0),
        end: Number(rec.end_second || 0),
        rec,
      }));

    const recordingIds = new Set(recordings.map(item => Number(item.rec.id)));
    const snapshots = (S.day?.events || [])
      .filter(event => includeFalsePositives || !ids.has(Number(event.id)))
      .filter(event => event.snapshot_url)
      .filter(event => !event.recording_id || !recordingIds.has(Number(event.recording_id)))
      .map(event => ({
        type: 'snapshot',
        start: Number(event.second || 0),
        end: Number(event.second || 0),
        event,
      }));

    const audio = (S.analysis?.audio_sessions || []).map(session => ({
      type: 'audio',
      start: Number(session.start_second || 0),
      end: Math.max(Number(session.end_second || session.start_second || 0), Number(session.start_second || 0) + 4),
      session,
    }));

    const rank = { recording: 0, snapshot: 1, audio: 2 };
    return [...recordings, ...snapshots, ...audio].sort((a, b) => {
      const delta = Number(a.start) - Number(b.start);
      if (Math.abs(delta) > .0001) return delta;
      const typeDelta = rank[a.type] - rank[b.type];
      if (typeDelta) return typeDelta;
      return itemKey(a).localeCompare(itemKey(b));
    });
  }

  function seekTarget(item) {
    const start = Number(item?.start || 0);
    const end = Number(item?.end || start);
    if (item?.rec && end > start) return Math.min(end - .005, start + .02);
    if (item?.type === 'audio') return start + .01;
    return start;
  }

  function seekExact(second) {
    const scrubber = el('poiDayScrubber');
    if (!scrubber) return;
    scrubber.step = '0.01';
    const max = Number(scrubber.max || S.day?.day_duration_seconds || 86400);
    const value = Math.max(0, Math.min(max, Number(second) || 0));
    scrubber.value = String(value);
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
    requestAnimationFrame(() => {
      if (document.activeElement !== scrubber) scrubber.value = String(value);
    });
  }

  function syncEventSelection(eventId) {
    const id = Number(eventId || 0) || null;
    const selectors = [
      '#poiV63ClipTrack [data-event-id]',
      '#poiV63EventTrack [data-event-id]',
      '#poiEventMarkers [data-event-id]',
      '#poiEventStrip [data-event-card]',
    ];
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach(node => {
        const nodeId = Number(node.dataset.eventId || node.dataset.eventCard || 0);
        node.classList.toggle('selected', Boolean(id && nodeId === id && !node.hidden));
      });
    }
    const classify = el('poiTimelineClassify');
    if (classify) {
      classify.hidden = !id;
      if (id) classify.dataset.eventId = String(id);
      else delete classify.dataset.eventId;
    }
  }

  function currentMediaKey(items) {
    const video = el('poiTimelineVideo');
    if (video && !video.hidden && Number(video.dataset.recordingId || 0)) {
      const key = `rec:${Number(video.dataset.recordingId)}`;
      if (items.some(item => itemKey(item) === key)) return key;
    }

    const audioOverlay = el('poiV66AudioOverlay');
    const selectedAudio = document.querySelector('#poiV66AudioTrack [data-audio-id].selected');
    if (audioOverlay && !audioOverlay.hidden && selectedAudio) {
      const key = `audio:${Number(selectedAudio.dataset.audioId)}`;
      if (items.some(item => itemKey(item) === key)) return key;
    }

    const snapshot = el('poiTimelineSnapshot');
    const selected = selectedEventId();
    if (snapshot && !snapshot.hidden && selected) {
      const key = `event:${selected}`;
      if (items.some(item => itemKey(item) === key)) return key;
    }

    if (S.navKey && items.some(item => itemKey(item) === S.navKey)) return S.navKey;

    if (selected) {
      const rec = items.find(item => item.rec && Number(item.rec.source_event_id || 0) === selected);
      if (rec) return itemKey(rec);
      const event = items.find(item => item.event && Number(item.event.id) === selected);
      if (event) return itemKey(event);
    }

    const now = playbackSecond();
    const containing = items.find(item => item.rec && Number(item.start) <= now && now <= Number(item.end));
    return containing ? itemKey(containing) : null;
  }

  function neighborByIndex(items, direction) {
    if (!items.length) return null;
    const key = currentMediaKey(items);
    if (key) {
      const index = items.findIndex(item => itemKey(item) === key);
      if (index >= 0) return items[index + direction] || null;
    }

    const now = playbackSecond();
    if (direction > 0) return items.find(item => Number(item.start) > now + .001) || null;
    for (let i = items.length - 1; i >= 0; i -= 1) {
      if (Number(items[i].start) < now - .001) return items[i];
    }
    return null;
  }

  function resumeHybridSoon() {
    setTimeout(() => {
      const play = el('poiHybridPlay');
      if (play && !play.textContent?.includes('❚')) play.click();
    }, 120);
  }

  function focusMediaItem(item, { resume = false } = {}) {
    if (!item) return;
    S.navKey = itemKey(item);

    if (item.type === 'audio') {
      const button = document.querySelector(`#poiV66AudioTrack [data-audio-id="${Number(item.session?.id)}"]`);
      if (button) button.click();
      requestAnimationFrame(() => seekExact(seekTarget(item)));
      return;
    }

    const eventId = itemEventId(item);
    syncEventSelection(eventId);
    const audioOverlay = el('poiV66AudioOverlay');
    if (audioOverlay) audioOverlay.hidden = true;
    seekExact(seekTarget(item));
    if (resume) resumeHybridSoon();
  }

  async function jumpMediaDeterministic(direction) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken || !S.day || !S.analysis) return;
    const items = mediaItems(showFalsePositives());
    const target = neighborByIndex(items, direction);
    if (!target) return;
    focusMediaItem(target, { resume: hybridPlaying() });
  }

  function bindNavigationOwner() {
    if (window.__poiV73FpNavigationBound) return;
    window.__poiV73FpNavigationBound = true;
    window.addEventListener('click', event => {
      if (!timelineActive()) return;
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
      if (!next && !previous) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void jumpMediaDeterministic(next ? 1 : -1);
    }, true);
  }

  function observeRenders() {
    if (S.observer) return;
    const root = el('poiTimelinePlayer');
    if (!root) return;
    S.observer = new MutationObserver(scheduleApplyFilter);
    S.observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['hidden', 'class', 'style', 'data-event-id', 'data-event-card', 'data-recording-id'],
    });
  }

  function invalidate() {
    S.day = null;
    S.analysis = null;
    S.key = '';
    S.lastSecond = null;
    S.navKey = null;
    S.navToken += 1;
  }

  function bindControls() {
    if (document.documentElement.dataset.poiV73FpBound === '1') return;
    document.documentElement.dataset.poiV73FpBound = '1';

    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => el(id)?.addEventListener('change', () => {
      invalidate();
      setTimeout(() => loadData(true).then(scheduleApplyFilter), 300);
    }));

    el('poiTimelineRefresh')?.addEventListener('click', () => {
      invalidate();
      setTimeout(() => loadData(true).then(scheduleApplyFilter), 260);
    });

    el('poiTimelineShowFp')?.addEventListener('change', () => {
      S.navKey = null;
      scheduleApplyFilter();
      setTimeout(scheduleApplyFilter, 100);
    });

    el('poiDayScrubber')?.addEventListener('input', event => {
      if (event.isTrusted) S.navKey = null;
    });
  }

  function init() {
    if (!el('poiTimelinePlayer')) return false;
    const scrubber = el('poiDayScrubber');
    if (scrubber) scrubber.step = '0.01';
    bindControls();
    bindVideoGuard();
    bindNavigationOwner();
    observeRenders();
    void loadData(true).then(scheduleApplyFilter);
    return true;
  }

  bindNavigationOwner();
  if (!init()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (init() || attempts > 120) clearInterval(timer);
    }, 100);
  }
})();
