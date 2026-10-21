(() => {
  const S = {
    day: null,
    analysis: null,
    key: '',
    loading: null,
    observer: null,
    lastSecond: null,
    navToken: 0,
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

  function falsePositiveIds() {
    return new Set((S.day?.events || [])
      .filter(item => String(item.identity_state || '') === 'false_positive')
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
    node.hidden = Boolean(filtered);
    if (filtered) {
      node.dataset.poiFpFiltered = '1';
      node.style.display = 'none';
      node.classList.remove('selected');
    } else if (node.dataset.poiFpFiltered === '1') {
      delete node.dataset.poiFpFiltered;
      node.style.removeProperty('display');
      node.hidden = false;
    }
  }

  function selectedEventId() {
    const classify = Number(el('poiTimelineClassify')?.dataset.eventId || 0);
    if (classify) return classify;
    const selectors = [
      '#poiV63ClipTrack [data-event-id].selected',
      '#poiV63EventTrack [data-event-id].selected',
      '#poiEventMarkers [data-event-id].selected',
      '#poiEventStrip [data-event-card].selected',
    ];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = Number(node?.dataset.eventId || node?.dataset.eventCard || 0);
      if (value) return value;
    }
    return null;
  }

  function hideVisualEventArtifacts() {
    const overlay = el('poiV63EventOverlay');
    const bbox = el('poiV66BBox');
    const classify = el('poiTimelineClassify');
    if (overlay) overlay.hidden = true;
    if (bbox) bbox.hidden = true;
    if (classify) {
      classify.hidden = true;
      delete classify.dataset.eventId;
    }
  }

  function clearHiddenSelection(ids) {
    const selected = selectedEventId();
    const overlaySaysFp = String(el('poiV63OverlayLabel')?.textContent || '').trim().toLowerCase() === 'falso positivo';
    if ((selected && ids.has(selected)) || overlaySaysFp) {
      document.querySelectorAll('.selected[data-event-id], .selected[data-event-card]').forEach(node => {
        const id = Number(node.dataset.eventId || node.dataset.eventCard || 0);
        if (ids.has(id)) node.classList.remove('selected');
      });
      hideVisualEventArtifacts();
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
  }

  function applyFilter() {
    if (!S.day) return;
    const ids = falsePositiveIds();
    const filtering = !showFalsePositives();
    const selectors = [
      ['#poiV63ClipTrack [data-event-id]', 'eventId'],
      ['#poiV63EventTrack [data-event-id]', 'eventId'],
      ['#poiEventMarkers [data-event-id]', 'eventId'],
      ['#poiEventStrip [data-event-card]', 'eventCard'],
    ];
    for (const [selector, key] of selectors) {
      document.querySelectorAll(selector).forEach(node => {
        const id = Number(node.dataset[key] || 0);
        setFiltered(node, filtering && id > 0 && ids.has(id));
      });
    }

    document.querySelectorAll('#poiCoverageTrack [data-recording-id]').forEach(node => {
      const rec = recordingById(node.dataset.recordingId);
      setFiltered(node, filtering && isHiddenFalsePositiveRecording(rec, ids));
    });

    if (filtering) {
      clearHiddenSelection(ids);
      clearHiddenCurrentRecording(ids);
    }
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
    const value = Math.max(0, Math.min(max, Number(second) || 0));
    scrubber.value = String(value);
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
      if (showFalsePositives() || !latest || String(latest.identity_state || '') !== 'false_positive') return;
      document.querySelectorAll('.selected[data-event-id], .selected[data-event-card]').forEach(node => {
        const id = Number(node.dataset.eventId || node.dataset.eventCard || 0);
        if (id === Number(latest.id)) node.classList.remove('selected');
      });
      hideVisualEventArtifacts();
    });
    video.addEventListener('seeking', () => {
      S.lastSecond = playbackSecond();
    });
  }

  function visualItems(includeFalsePositives) {
    const ids = falsePositiveIds();
    const recordings = (S.day?.recordings || [])
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .filter(rec => includeFalsePositives || String(rec.mode || '') !== 'event' || !rec.source_event_id || !ids.has(Number(rec.source_event_id)))
      .map(rec => ({
        type: 'visual',
        start: Number(rec.start_second || 0),
        end: Number(rec.end_second || 0),
        rec,
      }));
    const events = (S.day?.events || [])
      .filter(event => includeFalsePositives || !ids.has(Number(event.id)))
      .filter(event => event.snapshot_url)
      .filter(event => !recordings.some(item => item.start <= Number(event.second || 0) && Number(event.second || 0) <= item.end))
      .map(event => ({
        type: 'visual',
        start: Number(event.second || 0),
        end: Number(event.second || 0),
        event,
      }));
    return [...recordings, ...events].sort((a, b) => a.start - b.start);
  }

  function temporalItems(includeFalsePositives) {
    const visual = visualItems(includeFalsePositives);
    const audio = (S.analysis?.audio_sessions || []).map(session => ({
      type: 'audio',
      start: Number(session.start_second || 0),
      end: Math.max(Number(session.end_second || session.start_second || 0), Number(session.start_second || 0) + 4),
      session,
    }));
    return [...visual, ...audio].sort((a, b) => {
      const delta = Number(a.start) - Number(b.start);
      if (Math.abs(delta) > .001) return delta;
      if (a.type === b.type) return 0;
      return a.type === 'audio' ? -1 : 1;
    });
  }

  function temporalTarget(items, second, direction) {
    if (direction > 0) return items.find(item => Number(item.start) > Number(second) + .35) || null;
    const prior = items.filter(item => Number(item.start) < Number(second) - .35);
    return prior.length ? prior[prior.length - 1] : null;
  }

  function itemEventId(item) {
    return Number(item?.event?.id || item?.rec?.source_event_id || 0) || null;
  }

  function safeTemporalSecond(item) {
    const start = Number(item?.start || 0);
    const end = Number(item?.end || start);
    if (item?.rec && end > start) {
      const margin = Math.min(.08, Math.max(.01, (end - start) / 4));
      return Math.min(end - .005, start + margin);
    }
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

  function resumeHybridSoon() {
    setTimeout(() => {
      const play = el('poiHybridPlay');
      if (play && !play.textContent?.includes('❚')) play.click();
    }, 120);
  }

  function focusTemporalTarget(item, { resume = false } = {}) {
    if (!item) return;
    if (item.type === 'audio') {
      const button = document.querySelector(`#poiV66AudioTrack [data-audio-id="${Number(item.session?.id)}"]`);
      if (button) {
        button.click();
        requestAnimationFrame(() => seekExact(safeTemporalSecond(item)));
        return;
      }
      seekExact(safeTemporalSecond(item));
      return;
    }

    const eventId = itemEventId(item);
    syncEventSelection(eventId);
    const audioOverlay = el('poiV66AudioOverlay');
    if (audioOverlay) audioOverlay.hidden = true;
    seekExact(safeTemporalSecond(item));
    if (resume) resumeHybridSoon();
  }

  async function jumpTemporal(direction) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken || !S.day || !S.analysis) return;
    const items = temporalItems(showFalsePositives());
    const current = Number(el('poiDayScrubber')?.value || 0);
    const target = temporalTarget(items, current, direction);
    if (!target) return;
    const wasPlaying = hybridPlaying();
    focusTemporalTarget(target, { resume: wasPlaying });
  }

  function bindNavigationGuard() {
    if (window.__poiV73FpNavigationBound) return;
    window.__poiV73FpNavigationBound = true;
    window.addEventListener('click', event => {
      if (!timelineActive()) return;
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
      if (!next && !previous) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void jumpTemporal(next ? 1 : -1);
    }, true);
  }

  function observeRenders() {
    if (S.observer) return;
    const targets = [
      el('poiV63ClipTrack'),
      el('poiV63EventTrack'),
      el('poiEventMarkers'),
      el('poiEventStrip'),
      el('poiCoverageTrack'),
    ].filter(Boolean);
    if (!targets.length) return;
    S.observer = new MutationObserver(() => requestAnimationFrame(applyFilter));
    targets.forEach(target => S.observer.observe(target, { childList: true }));
  }

  function invalidate() {
    S.day = null;
    S.analysis = null;
    S.key = '';
    S.lastSecond = null;
    S.navToken += 1;
  }

  function bindControls() {
    if (document.documentElement.dataset.poiV73FpBound === '1') return;
    document.documentElement.dataset.poiV73FpBound = '1';
    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => el(id)?.addEventListener('change', () => {
      invalidate();
      setTimeout(() => loadData(true).then(applyFilter), 300);
    }));
    el('poiTimelineRefresh')?.addEventListener('click', () => {
      invalidate();
      setTimeout(() => loadData(true).then(applyFilter), 260);
    });
    el('poiTimelineShowFp')?.addEventListener('change', () => {
      applyFilter();
      setTimeout(applyFilter, 80);
    });
  }

  function init() {
    if (!el('poiTimelinePlayer')) return false;
    const scrubber = el('poiDayScrubber');
    if (scrubber) scrubber.step = '0.01';
    bindControls();
    bindVideoGuard();
    bindNavigationGuard();
    observeRenders();
    void loadData(true).then(applyFilter);
    return true;
  }

  bindNavigationGuard();
  if (!init()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (init() || attempts > 120) clearInterval(timer);
    }, 100);
  }
})();
