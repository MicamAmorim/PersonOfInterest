(() => {
  if (window.__poiPwaInstallLoaded) return;
  window.__poiPwaInstallLoaded = true;

  let deferredPrompt = null;
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent || '');
  const isStandalone = () =>
    window.matchMedia?.('(display-mode: standalone)')?.matches ||
    window.navigator.standalone === true;

  function esc(value = '') {
    return String(value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[ch]);
  }

  function ensureUi() {
    if (document.getElementById('pwaInstallBtn')) return;
    const actions = document.querySelector('.top-actions');
    if (!actions) return;

    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'pwaInstallBtn';
    button.className = 'button ghost poi-pwa-install hidden';
    button.textContent = '⬇ Instalar app';
    button.title = 'Instalar o PersonOfInterest neste aparelho';
    actions.prepend(button);

    const overlay = document.createElement('div');
    overlay.id = 'pwaInstallOverlay';
    overlay.className = 'poi-pwa-overlay hidden';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'pwaInstallTitle');
    overlay.innerHTML = `
      <div class="poi-pwa-card">
        <button type="button" class="poi-pwa-close" id="pwaInstallClose" aria-label="Fechar">×</button>
        <div class="poi-pwa-icon">⬡</div>
        <p class="eyebrow">PERSONOFINTEREST</p>
        <h2 id="pwaInstallTitle">Instalar aplicativo</h2>
        <div id="pwaInstallBody" class="poi-pwa-body"></div>
        <div class="poi-pwa-actions">
          <button type="button" class="button ghost" id="pwaInstallCancel">Agora não</button>
          <button type="button" class="button primary" id="pwaInstallConfirm">Instalar</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const close = () => overlay.classList.add('hidden');
    document.getElementById('pwaInstallClose')?.addEventListener('click', close);
    document.getElementById('pwaInstallCancel')?.addEventListener('click', close);
    overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
    document.getElementById('pwaInstallConfirm')?.addEventListener('click', performInstall);
    button.addEventListener('click', openInstallUi);

    syncButton();
  }

  function syncButton() {
    const button = document.getElementById('pwaInstallBtn');
    if (!button) return;
    if (isStandalone()) {
      button.classList.add('hidden');
      return;
    }
    // iOS never exposes beforeinstallprompt. On Chromium we show the button
    // once the native install prompt is available. Other browsers get a manual
    // install helper instead of a broken native action.
    const canGuide = isIOS || /android|chrome|chromium|edg|safari/i.test(navigator.userAgent || '');
    button.classList.toggle('hidden', !deferredPrompt && !canGuide);
  }

  function openInstallUi() {
    if (isStandalone()) return;
    ensureUi();
    const overlay = document.getElementById('pwaInstallOverlay');
    const body = document.getElementById('pwaInstallBody');
    const confirm = document.getElementById('pwaInstallConfirm');
    if (!overlay || !body || !confirm) return;

    if (deferredPrompt) {
      body.innerHTML = '<p>Instale o PersonOfInterest como aplicativo neste aparelho. Ele abrirá em janela própria, sem a barra normal do navegador.</p>';
      confirm.textContent = 'Instalar';
      confirm.classList.remove('hidden');
    } else if (isIOS) {
      body.innerHTML = `
        <p>No iPhone/iPad a instalação é feita pelo Safari:</p>
        <ol>
          <li>Abra este endereço no <strong>Safari</strong>.</li>
          <li>Toque em <strong>Compartilhar</strong> <span class="poi-pwa-share">⇧</span>.</li>
          <li>Escolha <strong>Adicionar à Tela de Início</strong>.</li>
          <li>Se aparecer, mantenha <strong>Abrir como App</strong> ativado.</li>
        </ol>`;
      confirm.textContent = 'Entendi';
      confirm.classList.remove('hidden');
    } else {
      body.innerHTML = `
        <p>Seu navegador ainda não liberou o prompt automático. Use o menu do navegador e escolha <strong>Instalar aplicativo</strong> ou <strong>Adicionar à tela inicial</strong>.</p>
        <p class="muted">A instalação exige HTTPS (como o endereço .ts.net do Tailscale Serve) ou localhost.</p>`;
      confirm.textContent = 'Entendi';
      confirm.classList.remove('hidden');
    }
    overlay.classList.remove('hidden');
  }

  async function performInstall() {
    const overlay = document.getElementById('pwaInstallOverlay');
    if (!deferredPrompt) {
      overlay?.classList.add('hidden');
      return;
    }
    const prompt = deferredPrompt;
    deferredPrompt = null;
    try {
      await prompt.prompt();
      await prompt.userChoice;
    } catch (_) {
      // Browser owns the native prompt lifecycle; a rejection is not an app error.
    }
    overlay?.classList.add('hidden');
    syncButton();
  }

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferredPrompt = event;
    ensureUi();
    syncButton();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    document.getElementById('pwaInstallOverlay')?.classList.add('hidden');
    syncButton();
    if (typeof toast === 'function') toast('PersonOfInterest instalado neste aparelho.');
  });

  try {
    window.matchMedia?.('(display-mode: standalone)')?.addEventListener?.('change', syncButton);
  } catch (_) {}

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureUi, { once: true });
  } else {
    ensureUi();
  }
})();
