(() => {
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
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (install() || attempts > 30) clearInterval(timer);
    }, 150);
  }
})();
