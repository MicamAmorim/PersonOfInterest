(() => {
  function timelineActive() {
    return Boolean(document.getElementById('timelineView')?.classList.contains('active'));
  }

  function isTypingTarget(target) {
    const tag = String(target?.tagName || '').toLowerCase();
    return ['input', 'textarea', 'select'].includes(tag) || Boolean(target?.isContentEditable);
  }

  function hybridPlaying() {
    const video = document.getElementById('poiTimelineVideo');
    const button = document.getElementById('poiHybridPlay');
    return Boolean((video && !video.hidden && !video.paused && !video.ended) || button?.textContent?.includes('❚'));
  }

  function toggleHybridPlayback() {
    const button = document.getElementById('poiHybridPlay');
    if (button) button.click();
  }

  function bindSpaceCapture() {
    document.addEventListener('keydown', event => {
      if (event.code !== 'Space' || event.repeat || !timelineActive()) return;
      if (document.querySelector('dialog[open]')) return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      toggleHybridPlayback();
    }, true);
  }

  function bindClipAutoplay() {
    document.addEventListener('click', event => {
      const clip = event.target.closest?.('#poiV63ClipTrack [data-v63-clip]');
      if (!clip) return;
      try { clip.blur(); } catch (_) {}
      const eventId = Number(clip.dataset.eventId || 0);
      if (eventId) {
        const card = document.querySelector(`#poiEventStrip [data-event-card="${eventId}"]`);
        if (card) {
          card.click();
          return;
        }
      }
      if (!hybridPlaying()) toggleHybridPlayback();
    });
  }

  function hardenVideoFit() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video) return;
    video.style.objectFit = 'contain';
    video.style.objectPosition = 'center center';
  }

  function init() {
    if (!document.getElementById('poiTimelinePlayer')) return false;
    bindSpaceCapture();
    bindClipAutoplay();
    hardenVideoFit();
    return true;
  }

  function wait() {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (document.getElementById('poiTimelinePlayer') && document.getElementById('poiHybridControls')) {
        clearInterval(timer);
        init();
      } else if (attempts > 120) clearInterval(timer);
    }, 100);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wait, { once: true });
  else wait();
})();
