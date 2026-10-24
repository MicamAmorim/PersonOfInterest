(() => {
  function bytes(value) {
    let n = Number(value) || 0;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
  }

  async function compactDatabase() {
    if (!confirm('Compactar o SQLite agora? Isso recupera espaço interno liberado por exclusões. O banco pode ficar brevemente ocupado durante o VACUUM; se houver escrita concorrente, a operação será cancelada sem interromper o motor.')) return;
    const button = document.getElementById('v59CompactDb');
    if (button) { button.disabled = true; button.textContent = 'Compactando…'; }
    try {
      const result = await api('/api/storage/compact', { method: 'POST', body: '{}' });
      toast(`Banco compactado: ${bytes(result.before_bytes)} → ${bytes(result.after_bytes)} · ${bytes(result.freed_bytes)} recuperados.`);
      if (typeof loadStorage === 'function') await loadStorage();
    } catch (error) {
      toast(`Compactação: ${error.message}`, 'error');
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Compactar banco'; }
    }
  }

  function install() {
    if (document.getElementById('v59CompactDb')) return true;
    const actions = document.querySelector('#v58StorageRoot .v58-actions');
    if (!actions) return false;
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'v59CompactDb';
    button.className = 'button ghost small';
    button.textContent = 'Compactar banco';
    button.title = 'Executa VACUUM manual para recuperar espaço físico do SQLite após exclusões.';
    button.addEventListener('click', compactDatabase);
    actions.insertBefore(button, actions.lastElementChild || null);
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (install() || attempts > 40) clearInterval(timer);
    }, 150);
  }
})();
