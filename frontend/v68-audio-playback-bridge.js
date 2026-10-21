(() => {
  const S = {
    analysis: null,
    day: null,
    key: '',
    loading: null,
    audioTimer: null,
  };

  function cameraId() {
    return Number(document.getElementById('poiTimelineCamera')?.value || 0) || null;
  }

  function dateValue() {
    return document.getElementById('poiTimelineDate')?.value || '';
  }

  function currentSecond() {
    return Number(document.getElementById('poiDayScrubber')?.value || 0) || 0;
  }

  function hybridPlaying() {
    const play = document.getElementById('poiHybridPlay');
    const video = document.getElementById('poiTimelineVideo');
    return Boolean(play?.textContent?.includes('❚') || (video && !video.hidden && !video.paused && !video.ended));
  }

  function pauseHybrid() {
    const play = document.getElementById('poiHybridPlay');
    if (play?.textContent?.includes('❚')) {
      play.click();
      return;
    }
    const video = document.getElementById('poiTimelineVideo');
    if (video && !video.hidden && !video.paused) {
      try { video.pause(); } catch (_) {}
    }
  }

  function pauseOnEvents() {
    return Boolean(document.getElementById('poiV63PauseEvents')?.checked);
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

  function audioButton(id) {
    return document.querySelector(`#poiV66AudioTrack [data-audio-id="${Number(id)}"]`);
  }

  function seekExact(second) {
    const scrubber = document.getElementById('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || S.analysis?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function clearVisualSelectionForAudio() {
    document.querySelectorAll('#poiV63EventTrack [data-event-id], #poiV63ClipTrack [data-event-id], #poiEventMarkers [data-event-id], #poiEventStrip [data-event-card]')
      .forEach(el => el.classList.remove('selected'));
    const eventOverlay = document.getElementById('poiV63EventOverlay');
    if (eventOverlay) eventOverlay.hidden = true;
    const bbox = document.getElementById('poiV66BBox');
    if (bbox) bbox.hidden = true;
    const classify = document.getElementById('poiTimelineClassify');
    if (classify) {
      classify.hidden = true;
      delete classify.dataset.eventId;
    }
  }

  function focusAudio(session, { fromPlayback = false } = {}) {
    if (!session) return;
    if (S.audioTimer) clearTimeout(S.audioTimer);
    const wasPlaying = fromPlayback || hybridPlaying();
    pauseHybrid();
    clearVisualSelectionForAudio();
    seekExact(Number(session.start_second || 0));
    setTimeout(() => {
      const button = audioButton(session.id);
      if (button) button.click();
    }, 20);

    if (wasPlaying && !pauseOnEvents()) {
      const visibleMs = Math.max(1600, Math.min(6000, (Number(session.duration_seconds || 4) * 650)));
      S.audioTimer = setTimeout(async () => {
        await loadData(false);
        const second = Number(session.end_second || session.start_second || 0) + .05;
        const a = nextAudio(second);
        const v = nextVisual(second);
        if (a && (!v || Number(a.start_second) < Number(v.start))) {
          focusAudio(a, { fromPlayback: true });
          return;
        }
        if (v) {
          seekExact(v.start);
          setTimeout(() => {
            const play = document.getElementById('poiHybridPlay');
            if (play && !play.textContent?.includes('❚')) play.click();
          }, 140);
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

  function bindAudioClicks() {
    document.addEventListener('click', event => {
      const audio = event.target.closest?.('#poiV66AudioTrack [data-audio-id]');
      if (!audio) return;
      // V6.6 performs the actual overlay rendering. We only make sure the hybrid
      // player is paused first, otherwise its scrubber-change handler immediately
      // advances to the next visual recording and places Tonho over the wrong clip.
      pauseHybrid();
      clearVisualSelectionForAudio();
    }, true);
  }

  function bindNextPrevious() {
    document.addEventListener('click', event => {
      const next = event.target.closest?.('#poiHybridNext');
      const previous = event.target.closest?.('#poiHybridPrev');
      if (!next && !previous) return;
      const direction = next ? 1 : -1;
      // Capture phase runs before V6.2's direct button listener. Decide whether
      // the nearest media in that direction is a Tonho session. If so, own this
      // click; otherwise leave the original visual navigation untouched.
      event.preventDefault();
      event.stopImmediatePropagation();
      void (async () => {
        const handled = await handleDirectional(direction);
        if (handled) return;
        // No Tonho session wins. Recreate the visual jump deterministically by
        // seeking to the nearest visual item and resuming if the user was playing.
        await loadData(false);
        const second = currentSecond();
        const visual = direction > 0 ? nextVisual(second) : previousVisual(second);
        if (!visual) return;
        const wasPlaying = hybridPlaying();
        seekExact(visual.start);
        if (wasPlaying) setTimeout(() => {
          const play = document.getElementById('poiHybridPlay');
          if (play && !play.textContent?.includes('❚')) play.click();
        }, 140);
      })();
    }, true);
  }

  function bindVideoEndBridge() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video || video.dataset.poiV68Ended === '1') return;
    video.dataset.poiV68Ended = '1';
    video.addEventListener('ended', () => {
      if (!hybridPlaying()) return;
      const second = currentSecond();
      void (async () => {
        await loadData(false);
        const audio = nextAudio(second);
        const visual = nextVisual(second);
        if (!audio || (visual && Number(visual.start) <= Number(audio.start_second))) return;
        // Beat V6.2's delayed advanceAfter(). focusAudio pauses its private
        // sequence state, so the older callback returns without skipping Tonho.
        setTimeout(() => focusAudio(audio, { fromPlayback: true }), 35);
      })();
    });
  }

  function invalidate() {
    S.analysis = null;
    S.day = null;
    S.key = '';
    if (S.audioTimer) clearTimeout(S.audioTimer);
    S.audioTimer = null;
  }

  function bindInvalidation() {
    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => document.getElementById(id)?.addEventListener('change', invalidate));
    document.getElementById('poiTimelineRefresh')?.addEventListener('click', invalidate);
  }

  function install() {
    if (!document.getElementById('poiTimelinePlayer') || !document.getElementById('poiV66AudioTrack')) return false;
    if (document.documentElement.dataset.poiV68Bound === '1') return true;
    document.documentElement.dataset.poiV68Bound = '1';
    bindAudioClicks();
    bindNextPrevious();
    bindVideoEndBridge();
    bindInvalidation();
    void loadData(true);
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (install() || attempts > 80) clearInterval(timer);
    }, 125);
  }
})();
