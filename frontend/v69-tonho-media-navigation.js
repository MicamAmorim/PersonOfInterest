(() => {
  const S = {
    analysis: null,
    day: null,
    key: '',
    loading: null,
    audioTimer: null,
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

  function focusAudio(session, { fromPlayback = false } = {}) {
    if (!session) return;
    if (S.audioTimer) clearTimeout(S.audioTimer);
    const wasPlaying = fromPlayback || hybridPlaying();
    pauseHybrid();
    clearVisualSelectionForAudio();
    seekExact(Number(session.start_second || 0));

    // Do not simulate a click on the audio track. V6.0 synchronously finishes its
    // visual selection first, then Tonho is rendered directly. If real video
    // covers this timestamp it stays underneath; otherwise V6.7 enters audio-only
    // mode and hides the generic "Escolha um ponto" placeholder.
    renderAudioOverlay(session);
    requestAnimationFrame(() => renderAudioOverlay(session));

    if (wasPlaying && !pauseOnEvents()) {
      const visibleMs = Math.max(1600, Math.min(6000, Number(session.duration_seconds || 4) * 650));
      S.audioTimer = setTimeout(async () => {
        await loadData(false);
        const after = Number(session.end_second || session.start_second || 0) + .05;
        const audio = nextAudio(after);
        const visual = nextVisual(after);
        if (audio && (!visual || Number(audio.start_second) < Number(visual.start))) {
          focusAudio(audio, { fromPlayback: true });
          return;
        }
        if (visual) {
          hideAudioOverlay();
          seekExact(visual.start);
          setTimeout(() => {
            const play = el('poiHybridPlay');
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
    // V6.8 listens on document capture. Window capture is deliberately used here
    // so the corrected navigation owns next/previous before the old bridge can
    // perform its click-based audio handoff.
    window.addEventListener('click', event => {
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
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
        hideAudioOverlay();
        seekExact(visual.start);
        if (wasPlaying) setTimeout(() => {
          const play = el('poiHybridPlay');
          if (play && !play.textContent?.includes('❚')) play.click();
        }, 120);
      })();
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
      focusAudio(session, { fromPlayback: false });
    }, true);
  }

  function invalidate() {
    S.analysis = null;
    S.day = null;
    S.key = '';
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
