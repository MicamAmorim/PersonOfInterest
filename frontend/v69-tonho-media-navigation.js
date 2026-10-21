(() => {
  const state69 = {
    analysis: null,
    day: null,
    key: '',
    loading: null,
    audioTimer: null,
  };

  const q = id => document.getElementById(id);

  function cameraId() {
    return Number(q('poiTimelineCamera')?.value || 0) || null;
  }

  function dateValue() {
    return q('poiTimelineDate')?.value || '';
  }

  function currentSecond() {
    return Number(q('poiDayScrubber')?.value || 0) || 0;
  }

  function pauseOnEvents() {
    return Boolean(q('poiV63PauseEvents')?.checked);
  }

  function hybridPlaying() {
    const play = q('poiHybridPlay');
    const video = q('poiTimelineVideo');
    return Boolean(play?.textContent?.includes('❚') || (video && !video.hidden && !video.paused && !video.ended));
  }

  function pauseHybrid() {
    const play = q('poiHybridPlay');
    if (play?.textContent?.includes('❚')) {
      play.click();
      return;
    }
    const video = q('poiTimelineVideo');
    if (video && !video.hidden && !video.paused) {
      try { video.pause(); } catch (_) {}
    }
  }

  async function loadData(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && state69.analysis && state69.day && state69.key === key) {
      return { analysis: state69.analysis, day: state69.day };
    }
    if (state69.loading && state69.key === key) return state69.loading;
    state69.key = key;
    const offset = -new Date().getTimezoneOffset();
    state69.loading = Promise.all([
      api(`/api/timeline-player/analysis?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
      api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`),
    ]).then(([analysis, day]) => {
      state69.analysis = analysis;
      state69.day = day;
      return { analysis, day };
    }).catch(() => null).finally(() => { state69.loading = null; });
    return state69.loading;
  }

  function audioSessions() {
    return Array.isArray(state69.analysis?.audio_sessions) ? state69.analysis.audio_sessions : [];
  }

  function visualItems() {
    const recordings = (state69.day?.recordings || [])
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .map(rec => ({ type: 'visual', start: Number(rec.start_second || 0), end: Number(rec.end_second || 0), rec }));
    const events = (state69.day?.events || [])
      .filter(event => event.snapshot_url)
      .filter(event => !recordings.some(item => item.start <= Number(event.second || 0) && Number(event.second || 0) <= item.end))
      .map(event => ({ type: 'visual', start: Number(event.second || 0), end: Number(event.second || 0), event }));
    return [...recordings, ...events].sort((a, b) => a.start - b.start);
  }

  function nextVisual(second) {
    return visualItems().find(item => item.start > Number(second) + .05) || null;
  }

  function previousVisual(second) {
    const items = visualItems().filter(item => item.start < Number(second) - .05);
    return items.length ? items[items.length - 1] : null;
  }

  function nextAudio(second) {
    return audioSessions().find(item => Number(item.start_second || 0) > Number(second) + .05) || null;
  }

  function previousAudio(second) {
    const items = audioSessions().filter(item => Number(item.start_second || 0) < Number(second) - .05);
    return items.length ? items[items.length - 1] : null;
  }

  function visualAt(second) {
    const t = Number(second) || 0;
    return visualItems().find(item => item.type === 'visual' && item.rec && item.start <= t && t <= item.end) || null;
  }

  function seekExact(second) {
    const scrubber = q('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || state69.analysis?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    // `input` updates the needle/clock. `change` asks V6.0 to render visual media
    // exactly at this timestamp. V6.9 immediately restores the Tonho focus after
    // that synchronous visual selection, so audio-only sessions never get stuck
    // on the generic empty-state and sessions inside real video stay over video.
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function clearVisualSelectionForAudio() {
    document.querySelectorAll('#poiV63EventTrack [data-event-id], #poiV63ClipTrack [data-event-id], #poiEventMarkers [data-event-id], #poiEventStrip [data-event-card]')
      .forEach(el => el.classList.remove('selected'));
    const eventOverlay = q('poiV63EventOverlay');
    if (eventOverlay) eventOverlay.hidden = true;
    const bbox = q('poiV66BBox');
    if (bbox) bbox.hidden = true;
    const classify = q('poiTimelineClassify');
    if (classify) {
      classify.hidden = true;
      delete classify.dataset.eventId;
    }
  }

  function directFocusAudio(session) {
    if (!session) return false;
    const direct = window.poiV66FocusAudioSession;
    if (typeof direct === 'function') {
      direct(session);
      return true;
    }
    // Backward-compatible fallback for a partially cached frontend. This is no
    // longer the normal path, but keeps the page usable while the service worker
    // finishes replacing older assets.
    const button = document.querySelector(`#poiV66AudioTrack [data-audio-id="${Number(session.id)}"]`);
    if (button) {
      button.click();
      return true;
    }
    return false;
  }

  function focusAudio(session, { fromPlayback = false } = {}) {
    if (!session) return;
    if (state69.audioTimer) clearTimeout(state69.audioTimer);
    const wasPlaying = fromPlayback || hybridPlaying();
    pauseHybrid();
    clearVisualSelectionForAudio();
    const second = Number(session.start_second || 0);
    seekExact(second);

    // V6.0's scrubber `change` listener is synchronous. Render Tonho directly in
    // the same task; do not wait for or simulate a DOM click on the audio track.
    directFocusAudio(session);
    requestAnimationFrame(() => directFocusAudio(session));

    if (wasPlaying && !pauseOnEvents()) {
      const visibleMs = Math.max(1600, Math.min(6000, Number(session.duration_seconds || 4) * 650));
      state69.audioTimer = setTimeout(async () => {
        await loadData(false);
        const after = Number(session.end_second || session.start_second || 0) + .05;
        const a = nextAudio(after);
        const v = nextVisual(after);
        if (a && (!v || Number(a.start_second) < Number(v.start))) {
          focusAudio(a, { fromPlayback: true });
          return;
        }
        if (v) {
          seekExact(v.start);
          setTimeout(() => {
            const play = q('poiHybridPlay');
            if (play && !play.textContent?.includes('❚')) play.click();
          }, 120);
        }
      }, visibleMs);
    }
  }

  async function handleDirectional(direction) {
    await loadData(false);
    const second = currentSecond();
    const audio = direction > 0 ? nextAudio(second) : previousAudio(second);
    const visual = direction > 0 ? nextVisual(second) : previousVisual(second);
    if (!audio) return false;
    const audioSecond = Number(audio.start_second || 0);
    const visualSecond = visual ? Number(visual.start || 0) : null;
    const audioWins = visualSecond == null || (direction > 0 ? audioSecond < visualSecond : audioSecond > visualSecond);
    if (!audioWins) return false;
    focusAudio(audio, { fromPlayback: hybridPlaying() });
    return true;
  }

  function bindNavigation() {
    document.addEventListener('click', event => {
      const next = event.target.closest?.('#poiHybridNext');
      const previous = event.target.closest?.('#poiHybridPrev');
      if (!next && !previous) return;
      const direction = next ? 1 : -1;
      event.preventDefault();
      event.stopImmediatePropagation();
      void (async () => {
        const handled = await handleDirectional(direction);
        if (handled) return;
        await loadData(false);
        const second = currentSecond();
        const visual = direction > 0 ? nextVisual(second) : previousVisual(second);
        if (!visual) return;
        const wasPlaying = hybridPlaying();
        seekExact(visual.start);
        if (wasPlaying) setTimeout(() => {
          const play = q('poiHybridPlay');
          if (play && !play.textContent?.includes('❚')) play.click();
        }, 120);
      })();
    }, true);
  }

  function bindAudioTrackClicks() {
    document.addEventListener('click', event => {
      const audio = event.target.closest?.('#poiV66AudioTrack [data-audio-id]');
      if (!audio) return;
      const session = audioSessions().find(item => Number(item.id) === Number(audio.dataset.audioId));
      if (!session) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      focusAudio(session, { fromPlayback: false });
    }, true);
  }

  function invalidate() {
    state69.analysis = null;
    state69.day = null;
    state69.key = '';
    if (state69.audioTimer) clearTimeout(state69.audioTimer);
    state69.audioTimer = null;
  }

  function bindInvalidation() {
    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => q(id)?.addEventListener('change', invalidate));
    q('poiTimelineRefresh')?.addEventListener('click', invalidate);
  }

  function install() {
    if (!q('poiTimelinePlayer') || !q('poiV66AudioTrack')) return false;
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
      if (install() || attempts > 100) clearInterval(timer);
    }, 100);
  }
})();
