(() => {
  const S = {
    analysis: null,
    day: null,
    key: '',
    loading: null,
    audioTimer: null,
    navToken: 0,
  };

  const el = id => document.getElementById(id);
  const esc = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function clock(seconds) {
    const total = Math.max(0, Math.min(86400, Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function timelineActive() {
    return Boolean(el('timelineView')?.classList.contains('active'));
  }

  function cameraId() {
    return Number(el('poiTimelineCamera')?.value || 0) || null;
  }

  function dateValue() {
    return el('poiTimelineDate')?.value || '';
  }

  function currentSecond() {
    return Number(el('poiDayScrubber')?.value || 0) || 0;
  }

  function pauseOnEvents() {
    return Boolean(el('poiV63PauseEvents')?.checked);
  }

  function hybridPlaying() {
    const play = el('poiHybridPlay');
    const video = el('poiTimelineVideo');
    return Boolean(play?.textContent?.includes('❚') || (video && !video.hidden && !video.paused && !video.ended));
  }

  function pauseHybrid() {
    const play = el('poiHybridPlay');
    if (play?.textContent?.includes('❚')) {
      play.click();
      return;
    }
    const video = el('poiTimelineVideo');
    if (video && !video.hidden && !video.paused) {
      try { video.pause(); } catch (_) {}
    }
  }

  async function loadData(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && S.analysis && S.day && S.key === key) return { analysis: S.analysis, day: S.day };
    if (S.loading && S.key === key) return S.loading;
    S.key = key;
    const offset = -new Date().getTimezoneOffset();
    S.loading = Promise.all([
      api(`/api/timeline-player/analysis?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
      api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
    ]).then(([analysis, day]) => {
      S.analysis = analysis;
      S.day = day;
      return { analysis, day };
    }).catch(() => null).finally(() => { S.loading = null; });
    return S.loading;
  }

  function audioSessions() {
    return Array.isArray(S.analysis?.audio_sessions) ? S.analysis.audio_sessions : [];
  }

  function visualItems() {
    const recordings = (S.day?.recordings || [])
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .map(rec => ({ type: 'visual', start: Number(rec.start_second || 0), end: Number(rec.end_second || 0), rec }));
    const events = (S.day?.events || [])
      .filter(event => event.snapshot_url)
      .filter(event => !recordings.some(item => item.start <= Number(event.second || 0) && Number(event.second || 0) <= item.end))
      .map(event => ({ type: 'visual', start: Number(event.second || 0), end: Number(event.second || 0), event }));
    return [...recordings, ...events].sort((a, b) => a.start - b.start);
  }

  function temporalItems() {
    const visual = visualItems();
    const audio = audioSessions().map(session => ({
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

  function visualAt(second) {
    const t = Number(second) || 0;
    const items = visualItems();
    return items.find(item => item.rec && item.start <= t && t <= item.end)
      || items.find(item => !item.rec && Math.abs(item.start - t) <= 1)
      || null;
  }

  function audioAt(second) {
    const t = Number(second) || 0;
    return audioSessions().find(session => {
      const start = Number(session.start_second || 0);
      const end = Math.max(Number(session.end_second || start), start + 4);
      return start <= t && t <= end;
    }) || null;
  }

  function nextTemporal(second) {
    const threshold = Number(second) + .35;
    return temporalItems().find(item => Number(item.start) > threshold) || null;
  }

  function previousTemporal(second) {
    const threshold = Number(second) - .35;
    const items = temporalItems().filter(item => Number(item.start) < threshold);
    return items.length ? items[items.length - 1] : null;
  }

  function seekExact(second) {
    const scrubber = el('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || S.analysis?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function clearVisualSelectionForAudio() {
    document.querySelectorAll('#poiV63EventTrack [data-event-id], #poiV63ClipTrack [data-event-id], #poiEventMarkers [data-event-id], #poiEventStrip [data-event-card]')
      .forEach(node => node.classList.remove('selected'));
    const eventOverlay = el('poiV63EventOverlay');
    if (eventOverlay) eventOverlay.hidden = true;
    const bbox = el('poiV66BBox');
    if (bbox) bbox.hidden = true;
    const classify = el('poiTimelineClassify');
    if (classify) {
      classify.hidden = true;
      delete classify.dataset.eventId;
    }
  }

  function hideAudioOverlay() {
    const overlay = el('poiV66AudioOverlay');
    if (overlay) overlay.hidden = true;
    document.querySelectorAll('#poiV66AudioTrack [data-audio-id]').forEach(node => node.classList.remove('selected'));
    if (S.audioTimer) clearTimeout(S.audioTimer);
    S.audioTimer = null;
  }

  function renderAudioOverlay(session) {
    const overlay = el('poiV66AudioOverlay');
    if (!overlay || !session) return false;
    document.querySelectorAll('#poiV66AudioTrack [data-audio-id]').forEach(node => {
      node.classList.toggle('selected', Number(node.dataset.audioId) === Number(session.id));
    });
    const time = el('poiV66AudioTime');
    const turns = el('poiV66AudioTurns');
    if (time) time.textContent = clock(session.start_second);
    if (turns) {
      turns.innerHTML = (session.turns || []).map(turn => `
        <div class="poi-v66-audio-turn">
          <b>Você</b><p>${esc(turn.user || '—')}</p>
          <b class="tonho">Tonho</b><p>${esc(turn.tonho || '—')}</p>
        </div>`).join('') || '<div class="poi-v66-audio-turn"><p>Wake do Tonho detectado.</p></div>';
    }
    overlay.hidden = false;
    return true;
  }

  function resumeHybridSoon() {
    setTimeout(() => {
      const play = el('poiHybridPlay');
      if (play && !play.textContent?.includes('❚')) play.click();
    }, 120);
  }

  function scheduleAudioContinuation(session, wasPlaying) {
    if (!wasPlaying || pauseOnEvents()) return;
    if (S.audioTimer) clearTimeout(S.audioTimer);
    const visibleMs = Math.max(1600, Math.min(6000, Number(session.duration_seconds || 4) * 650));
    S.audioTimer = setTimeout(async () => {
      await loadData(false);
      const after = Number(session.end_second || session.start_second || 0) + .35;
      const next = nextTemporal(after);
      if (!next) return;
      await showTemporalItem(next, { resume: true });
    }, visibleMs);
  }

  function focusAudio(session, { fromPlayback = false, seek = true } = {}) {
    if (!session) return;
    const wasPlaying = fromPlayback || hybridPlaying();
    if (S.audioTimer) clearTimeout(S.audioTimer);
    pauseHybrid();
    clearVisualSelectionForAudio();
    if (seek) seekExact(Number(session.start_second || 0));
    renderAudioOverlay(session);
    requestAnimationFrame(() => renderAudioOverlay(session));
    scheduleAudioContinuation(session, wasPlaying);
  }

  async function showTemporalItem(item, { resume = false } = {}) {
    if (!item) return;
    if (item.type === 'audio') {
      focusAudio(item.session, { fromPlayback: resume, seek: true });
      return;
    }
    hideAudioOverlay();
    seekExact(Number(item.start || 0));
    if (resume) resumeHybridSoon();
  }

  async function jumpTemporal(direction) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken) return;
    const second = currentSecond();
    const item = direction > 0 ? nextTemporal(second) : previousTemporal(second);
    if (!item) return;
    const wasPlaying = hybridPlaying();
    await showTemporalItem(item, { resume: wasPlaying });
  }

  async function seekRelativeOwned(delta) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken) return;
    const max = Number(el('poiDayScrubber')?.max || S.analysis?.day_duration_seconds || 86400);
    const target = Math.max(0, Math.min(max, currentSecond() + Number(delta || 0)));
    const wasPlaying = hybridPlaying();
    if (S.audioTimer) clearTimeout(S.audioTimer);
    pauseHybrid();
    hideAudioOverlay();
    seekExact(target);

    const session = audioAt(target);
    const visual = visualAt(target);
    if (session) {
      clearVisualSelectionForAudio();
      renderAudioOverlay(session);
      if (wasPlaying && visual && !pauseOnEvents()) {
        resumeHybridSoon();
        S.audioTimer = setTimeout(hideAudioOverlay, 5200);
      } else {
        scheduleAudioContinuation(session, wasPlaying);
      }
      return;
    }
    if (wasPlaying && visual) resumeHybridSoon();
  }

  function bindNavigation() {
    // Own all four navigation buttons before V6.2/V6.8 listeners. Keeping one
    // owner prevents the same click from being interpreted twice by different
    // generations of the hybrid player.
    window.addEventListener('click', event => {
      if (!timelineActive()) return;
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
      const forward = event.target?.closest?.('#poiHybridForward');
      const back = event.target?.closest?.('#poiHybridBack');
      if (!next && !previous && !forward && !back) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (next) void jumpTemporal(1);
      else if (previous) void jumpTemporal(-1);
      else if (forward) void seekRelativeOwned(10);
      else if (back) void seekRelativeOwned(-10);
    }, true);
  }

  function bindAudioTrackClicks() {
    window.addEventListener('click', event => {
      const target = event.target?.closest?.('#poiV66AudioTrack [data-audio-id]');
      if (!target) return;
      const session = audioSessions().find(item => Number(item.id) === Number(target.dataset.audioId));
      if (!session) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      focusAudio(session, { fromPlayback: false, seek: true });
    }, true);
  }

  function invalidate() {
    S.analysis = null;
    S.day = null;
    S.key = '';
    S.navToken += 1;
    if (S.audioTimer) clearTimeout(S.audioTimer);
    S.audioTimer = null;
  }

  function bindInvalidation() {
    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => el(id)?.addEventListener('change', invalidate));
    el('poiTimelineRefresh')?.addEventListener('click', invalidate);
  }

  function install() {
    if (!el('poiTimelinePlayer') || !el('poiV66AudioTrack') || !el('poiV66AudioOverlay')) return false;
    if (document.documentElement.dataset.poiV69Bound === '1') return true;
    document.documentElement.dataset.poiV69Bound = '1';
    bindNavigation();
    bindAudioTrackClicks();
    bindInvalidation();
    void loadData(true);
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (install() || attempts > 120) clearInterval(timer);
    }, 100);
  }
})();
