(() => {
  const S = {
    day: null,
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

  function showFalsePositives() {
    return Boolean(el('poiTimelineShowFp')?.checked);
  }

  function falsePositiveIds() {
    return new Set((S.day?.events || [])
      .filter(item => String(item.identity_state || '') === 'false_positive')
      .map(item => Number(item.id))
      .filter(Number.isFinite));
  }

  async function loadDay(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && S.day && S.key === key) return S.day;
    if (S.loading && S.key === key) return S.loading;
    S.key = key;
    const offset = -new Date().getTimezoneOffset();
    S.loading = api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`)
      .then(day => {
        S.day = day;
        return day;
      })
      .catch(() => S.day)
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

  function observeRenders() {
    if (S.observer) return;
    const targets = [el('poiV63ClipTrack'), el('poiV63EventTrack'), el('poiEventMarkers'), el('poiEventStrip')].filter(Boolean);
    if (!targets.length) return;
    S.observer = new MutationObserver(() => requestAnimationFrame(applyFilter));
    targets.forEach(target => S.observer.observe(target, { childList: true }));
  }

  function invalidate() {
    S.day = null;
    S.key = '';
    S.lastSecond = null;
  }

  function bindControls() {
    if (document.documentElement.dataset.poiV73FpBound === '1') return;
    document.documentElement.dataset.poiV73FpBound = '1';
    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => el(id)?.addEventListener('change', () => {
      invalidate();
      setTimeout(() => loadDay(true).then(applyFilter), 300);
    }));
    el('poiTimelineRefresh')?.addEventListener('click', () => {
      invalidate();
      setTimeout(() => loadDay(true).then(applyFilter), 260);
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
    observeRenders();
    await loadDay(true);
    applyFilter();
    return true;
  }

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
