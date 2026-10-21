(() => {
  const S = {
    day: null,
    analysis: null,
    key: '',
    loading: null,
    observer: null,
    lastSecond: null,
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

  function falsePositiveIds() {
    return new Set((S.day?.events || [])
      .filter(item => String(item.identity_state || '') === 'false_positive')
      .map(item => Number(item.id))
      .filter(Number.isFinite));
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

  function clearHiddenSelection(ids) {
    const selected = selectedEventId();
    const overlay = el('poiV63EventOverlay');
    const bbox = el('poiV66BBox');
    const classify = el('poiTimelineClassify');
    const overlaySaysFp = String(el('poiV63OverlayLabel')?.textContent || '').trim().toLowerCase() === 'falso positivo';
    if ((selected && ids.has(selected)) || overlaySaysFp) {
      document.querySelectorAll('.selected[data-event-id], .selected[data-event-card]').forEach(node => {
        const id = Number(node.dataset.eventId || node.dataset.eventCard || 0);
        if (ids.has(id)) node.classList.remove('selected');
      });
      if (overlay) overlay.hidden = true;
      if (bbox) bbox.hidden = true;
      if (classify) {
        classify.hidden = true;
        delete classify.dataset.eventId;
      }
    }
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
    if (filtering) clearHiddenSelection(ids);
  }

  function latestCrossedEvent(last, now) {
    if (!S.day || last == null || now < last || now - last > 5) return null;
    const crossed = (S.day.events || [])
      .filter(item => Number(item.second) > last && Number(item.second) <= now + .45)
      .sort((a, b) => Number(a.second) - Number(b.second));
    return crossed.length ? crossed[crossed.length - 1] : null;
  }

  function bindVideoGuard() {
    const video = el('poiTimelineVideo');
    if (!video || video.dataset.poiV73FpBound === '1') return;
    video.dataset.poiV73FpBound = '1';
    video.addEventListener('timeupdate', () => {
      const now = Number(el('poiDayScrubber')?.value || 0);
      const latest = latestCrossedEvent(S.lastSecond, now);
      S.lastSecond = now;
      if (showFalsePositives() || !latest || String(latest.identity_state || '') !== 'false_positive') return;
      const bbox = el('poiV66BBox');
      if (bbox) bbox.hidden = true;
      const overlay = el('poiV63EventOverlay');
      if (String(el('poiV63OverlayLabel')?.textContent || '').trim().toLowerCase() === 'falso positivo' && overlay) overlay.hidden = true;
    });
    video.addEventListener('seeking', () => {
      S.lastSecond = Number(el('poiDayScrubber')?.value || 0);
    });
  }

  function visualItems(includeFalsePositives) {
    const ids = falsePositiveIds();
    const recordings = (S.day?.recordings || [])
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .filter(rec => includeFalsePositives || rec.mode !== 'event' || !rec.source_event_id || !ids.has(Number(rec.source_event_id)))
      .map(rec => ({
        type: 'visual',
        start: Number(rec.start_second || 0),
        end: Number(rec.end_second || 0),
        rec,
        hiddenFalsePositive: !includeFalsePositives && rec.source_event_id && ids.has(Number(rec.source_event_id)),
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
        hiddenFalsePositive: !includeFalsePositives && ids.has(Number(event.id)),
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
      hiddenFalsePositive: false,
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

  function isHiddenFalsePositive(item) {
    if (!item || item.type !== 'visual' || showFalsePositives()) return false;
    const id = itemEventId(item);
    return Boolean(id && falsePositiveIds().has(id));
  }

  function seekExact(second) {
    const scrubber = el('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || S.day?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function focusFilteredTarget(item) {
    if (!item) return;
    if (item.type === 'audio') {
      const button = document.querySelector(`#poiV66AudioTrack [data-audio-id="${Number(item.session?.id)}"]`);
      if (button) {
        button.click();
        return;
      }
      seekExact(item.start);
      return;
    }
    const eventId = itemEventId(item);
    if (eventId) {
      const button = document.querySelector(`#poiV63ClipTrack [data-event-id="${eventId}"]:not([hidden]), #poiV63EventTrack [data-event-id="${eventId}"]:not([hidden]), #poiEventStrip [data-event-card="${eventId}"]:not([hidden])`);
      if (button) {
        button.click();
        return;
      }
    }
    seekExact(item.start);
  }

  function bindNavigationGuard() {
    if (window.__poiV73FpNavigationBound) return;
    window.__poiV73FpNavigationBound = true;
    window.addEventListener('click', event => {
      if (!timelineActive() || showFalsePositives() || !S.day || !S.analysis) return;
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
      if (!next && !previous) return;
      const direction = next ? 1 : -1;
      const current = Number(el('poiDayScrubber')?.value || 0);
      const rawTarget = temporalTarget(temporalItems(true), current, direction);
      if (!isHiddenFalsePositive(rawTarget)) return;
      const visibleTarget = temporalTarget(temporalItems(false), current, direction);
      event.preventDefault();
      event.stopImmediatePropagation();
      if (visibleTarget) focusFilteredTarget(visibleTarget);
    }, true);
  }

  function observeRenders() {
    if (S.observer) return;
    const targets = [el('poiV63ClipTrack'), el('poiV63EventTrack'), el('poiEventMarkers'), el('poiEventStrip')].filter(Boolean);
    if (!targets.length) return;
    S.observer = new MutationObserver(() => requestAnimationFrame(applyFilter));
    targets.forEach(target => S.observer.observe(target, { childList: true }));
  }

  function invalidate() {
    S.day = null;
    S.analysis = null;
    S.key = '';
    S.lastSecond = null;
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

  async function init() {
    if (!el('poiTimelinePlayer')) return false;
    bindControls();
    bindVideoGuard();
    bindNavigationGuard();
    observeRenders();
    await loadData(true);
    applyFilter();
    return true;
  }

  bindNavigationGuard();
  if (!init()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (el('poiTimelinePlayer')) {
        clearInterval(timer);
        void init();
      } else if (attempts > 120) clearInterval(timer);
    }, 100);
  }
})();
