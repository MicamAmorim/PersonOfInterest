(() => {
  function loadV5Assets() {
    if (!document.querySelector('link[data-poi-v50]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v50-persistent.css';
      link.dataset.poiV50 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v52]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v52-library-viewer.css';
      link.dataset.poiV52 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v53]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v53-doorbell.css';
      link.dataset.poiV53 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v54]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v54-pwa.css';
      link.dataset.poiV54 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v62]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v62-hybrid-playback.css';
      link.dataset.poiV62 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v63]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v63-timeline-tracks.css';
      link.dataset.poiV63 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v64]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v64-playback-picker-fixes.css';
      link.dataset.poiV64 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v66]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v66-event-overlay-audio-track.css';
      link.dataset.poiV66 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v67]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v67-timeline-overlay-layout.css';
      link.dataset.poiV67 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('link[data-poi-v70]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/v70-full-diagnostics.css';
      link.dataset.poiV70 = '1';
      document.head.appendChild(link);
    }
    if (!document.querySelector('script[data-poi-v50]')) {
      const script = document.createElement('script');
      script.src = '/v50-persistent.js';
      script.defer = true;
      script.dataset.poiV50 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v51]')) {
      const script = document.createElement('script');
      script.src = '/v51-live-overlay.js';
      script.defer = true;
      script.dataset.poiV51 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v52]')) {
      const script = document.createElement('script');
      script.src = '/v52-library-viewer.js';
      script.defer = true;
      script.dataset.poiV52 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v53]')) {
      const script = document.createElement('script');
      script.src = '/v53-doorbell.js';
      script.defer = true;
      script.dataset.poiV53 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v54]')) {
      const script = document.createElement('script');
      script.src = '/v54-pwa.js';
      script.defer = true;
      script.dataset.poiV54 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v57-push]')) {
      const script = document.createElement('script');
      script.src = '/v57-device-push.js';
      script.defer = true;
      script.dataset.poiV57Push = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v62]')) {
      const script = document.createElement('script');
      script.src = '/v62-hybrid-playback.js';
      script.defer = true;
      script.dataset.poiV62 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v63]')) {
      const script = document.createElement('script');
      script.src = '/v63-timeline-tracks.js';
      script.defer = true;
      script.dataset.poiV63 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v64]')) {
      const script = document.createElement('script');
      script.src = '/v64-playback-picker-fixes.js';
      script.defer = true;
      script.dataset.poiV64 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v66]')) {
      const script = document.createElement('script');
      script.src = '/v66-event-overlay-audio-track.js';
      script.defer = true;
      script.dataset.poiV66 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v67]')) {
      const script = document.createElement('script');
      script.src = '/v67-timeline-overlay-layout.js';
      script.defer = true;
      script.dataset.poiV67 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v68]')) {
      const script = document.createElement('script');
      script.src = '/v68-audio-playback-bridge.js';
      script.defer = true;
      script.dataset.poiV68 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v69]')) {
      const script = document.createElement('script');
      script.src = '/v69-tonho-media-navigation.js';
      script.defer = true;
      script.dataset.poiV69 = '1';
      document.body.appendChild(script);
    }
    if (!document.querySelector('script[data-poi-v70]')) {
      const script = document.createElement('script');
      script.src = '/v70-full-diagnostics.js';
      script.defer = true;
      script.dataset.poiV70 = '1';
      document.body.appendChild(script);
    }
  }

  function install() {
    const actions = document.querySelector('#identityView .identity-actions');
    if (!actions || document.getElementById('identityExportDiagnostics')) return false;

    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'identityExportDiagnostics';
    button.className = 'button ghost small';
    button.textContent = '⇩ Exportar diagnóstico';
    button.title = 'Exporta metadados e similaridades derivadas para calibração, sem imagens, RTSP ou embeddings brutos.';
    button.addEventListener('click', () => {
      const raw = prompt('Quantos dias incluir no diagnóstico?', '30');
      if (raw === null) return;
      const days = Math.max(1, Math.min(3650, Number(raw) || 30));
      const params = new URLSearchParams({
        days: String(days),
        max_samples: '500',
        pair_limit: '50000',
      });
      window.location.href = `/api/identity/diagnostics/export?${params.toString()}`;
    });
    actions.prepend(button);
    loadV5Assets();
    return true;
  }

  loadV5Assets();
  if (!install()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (install() || attempts > 30) clearInterval(timer);
    }, 150);
  }
})();
