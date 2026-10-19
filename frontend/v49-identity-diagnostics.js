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
