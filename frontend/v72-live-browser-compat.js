(() => {
  const VERSION = 'v7.2.2';

  function browserCameraUrl(cameraId, { listen = false, microphone = false } = {}) {
    const params = new URLSearchParams({
      camera_id: String(cameraId || ''),
      listen: listen ? '1' : '0',
      microphone: microphone ? '1' : '0',
      v: VERSION,
    });
    return `/camera-webrtc.html?${params.toString()}`;
  }

  window.poiBrowserCameraUrl = browserCameraUrl;

  function normalizeDashboardCards(root = document) {
    root.querySelectorAll?.('.camera-card[data-id]').forEach(card => {
      const iframe = card.querySelector('.camera-preview iframe');
      if (!iframe) return;
      const cameraId = Number(card.dataset.id || 0);
      if (!cameraId) return;
      const desired = browserCameraUrl(cameraId);
      const current = iframe.getAttribute('src') || '';
      if (current !== desired) iframe.setAttribute('src', desired);
    });
  }

  function normalizeViewer() {
    if (typeof window.viewerMediaUrl === 'function' && !window.viewerMediaUrl._poiV722) {
      const replacement = function(camera, speakerOn, micOn) {
        return browserCameraUrl(camera?.id, {
          listen: Boolean(speakerOn),
          microphone: Boolean(micOn),
        });
      };
      replacement._poiV722 = true;
      window.viewerMediaUrl = replacement;
    }
  }

  function normalizeTimelineLive() {
    const live = document.getElementById('poiTimelineLive');
    const cameraSelect = document.getElementById('poiTimelineCamera');
    if (!live || !cameraSelect) return;
    const current = live.getAttribute('src') || '';
    if (!current || current === 'about:blank' || current.includes('/camera-webrtc.html?')) return;
    const cameraId = Number(cameraSelect.value || 0);
    if (!cameraId) return;
    live.setAttribute('src', browserCameraUrl(cameraId));
  }

  function install() {
    normalizeViewer();
    normalizeDashboardCards();
    normalizeTimelineLive();

    const observer = new MutationObserver(mutations => {
      let dashboardTouched = false;
      let timelineTouched = false;
      for (const mutation of mutations) {
        if (mutation.type === 'childList') dashboardTouched = true;
        if (mutation.type === 'attributes' && mutation.target?.id === 'poiTimelineLive') timelineTouched = true;
      }
      if (dashboardTouched) normalizeDashboardCards();
      if (timelineTouched) normalizeTimelineLive();
    });

    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['src'],
    });

    document.addEventListener('change', event => {
      if (event.target?.id === 'poiTimelineCamera') setTimeout(normalizeTimelineLive, 0);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();
