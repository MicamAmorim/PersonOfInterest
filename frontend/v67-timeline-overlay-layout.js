(() => {
  const AUDIO_ONLY_CLASS = 'poi-v67-audio-only';
  const AUDIO_TITLE = 'Conversa com Tonho';

  function stage() {
    return document.getElementById('poiTimelineStage');
  }

  function audioOverlay() {
    return document.getElementById('poiV66AudioOverlay');
  }

  function visualMediaVisible() {
    return ['poiTimelineVideo', 'poiTimelineLive', 'poiTimelineSnapshot'].some(id => {
      const el = document.getElementById(id);
      return Boolean(el && !el.hidden);
    });
  }

  function audioVisible() {
    const overlay = audioOverlay();
    return Boolean(overlay && !overlay.hidden);
  }

  function clearStaleVisualSelection() {
    document.querySelectorAll('#poiV63EventTrack [data-event-id], #poiV63ClipTrack [data-event-id], #poiEventStrip [data-event-card]')
      .forEach(el => el.classList.remove('selected'));
    const eventOverlay = document.getElementById('poiV63EventOverlay');
    if (eventOverlay) eventOverlay.hidden = true;
    const bbox = document.getElementById('poiV66BBox');
    if (bbox) bbox.hidden = true;
  }

  function enterAudioOnly() {
    const s = stage();
    if (!s) return;
    const title = document.getElementById('poiMediaTitle');
    if (!s.classList.contains(AUDIO_ONLY_CLASS)) {
      if (title && title.textContent !== AUDIO_TITLE) {
        s.dataset.poiV67PreviousTitle = title.textContent || '';
      }
      s.classList.add(AUDIO_ONLY_CLASS);
    }
    if (title) title.textContent = AUDIO_TITLE;
    clearStaleVisualSelection();
  }

  function leaveAudioOnly() {
    const s = stage();
    if (!s || !s.classList.contains(AUDIO_ONLY_CLASS)) return;
    s.classList.remove(AUDIO_ONLY_CLASS);
    const title = document.getElementById('poiMediaTitle');
    if (title && title.textContent === AUDIO_TITLE) {
      const previous = s.dataset.poiV67PreviousTitle;
      title.textContent = previous || 'Selecione um horário';
    }
    delete s.dataset.poiV67PreviousTitle;
  }

  function syncLayout() {
    if (!document.getElementById('timelineView')?.classList.contains('active')) return;
    if (audioVisible() && !visualMediaVisible()) enterAudioOnly();
    else leaveAudioOnly();
  }

  function scheduleSync(delay = 0) {
    setTimeout(syncLayout, delay);
  }

  function bind() {
    if (document.documentElement.dataset.poiV67Bound === '1') return;
    document.documentElement.dataset.poiV67Bound = '1';

    document.addEventListener('click', event => {
      if (event.target.closest?.('#poiV66AudioTrack [data-audio-id]')) {
        scheduleSync(40);
        scheduleSync(180);
        return;
      }
      if (event.target.closest?.('#poiV66AudioClose')) {
        scheduleSync(0);
        return;
      }
      if (event.target.closest?.('#poiV63EventTrack [data-event-id], #poiV63ClipTrack [data-event-id], #poiEventStrip [data-event-card]')) {
        leaveAudioOnly();
      }
    });

    const scrubber = document.getElementById('poiDayScrubber');
    scrubber?.addEventListener('change', () => scheduleSync(120));

    ['poiTimelineVideo', 'poiTimelineLive', 'poiTimelineSnapshot'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      ['load', 'loadeddata', 'play', 'pause'].forEach(name => el.addEventListener(name, () => scheduleSync(0)));
    });

    // V6.6 can show/hide the Tonho overlay while playback crosses a wake event.
    // Observe only the overlay's `hidden` attribute. The callback never mutates
    // that attribute, so it cannot recurse like the old player observer bug.
    const overlay = audioOverlay();
    if (overlay && !overlay.dataset.poiV67Observed) {
      overlay.dataset.poiV67Observed = '1';
      const observer = new MutationObserver(() => scheduleSync(0));
      observer.observe(overlay, { attributes: true, attributeFilter: ['hidden'] });
    }

    syncLayout();
  }

  function installWhenReady() {
    if (stage() && audioOverlay()) {
      bind();
      return;
    }
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (stage() && audioOverlay()) {
        clearInterval(timer);
        bind();
      } else if (attempts > 60) {
        clearInterval(timer);
      }
    }, 150);
  }

  installWhenReady();
})();
