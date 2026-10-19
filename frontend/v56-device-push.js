(() => {
  const BUTTON_ID = 'devicePushPauseBtn';
  const STATUS_ID = 'devicePushPauseStatus';
  let busy = false;
  let currentEnabled = null;

  function supported() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  }

  async function currentSubscription() {
    if (!supported() || !window.isSecureContext) return null;
    const registration = await navigator.serviceWorker.ready;
    return registration.pushManager.getSubscription();
  }

  function setStatus(text, tone = '') {
    const el = document.getElementById(STATUS_ID);
    if (!el) return;
    el.textContent = text;
    el.dataset.tone = tone;
  }

  function renderButton() {
    const button = document.getElementById(BUTTON_ID);
    if (!button) return;
    button.disabled = busy || currentEnabled === null;
    button.textContent = currentEnabled === false
      ? 'Retomar neste dispositivo'
      : 'Pausar neste dispositivo';
    button.classList.toggle('primary', currentEnabled === false);
    button.classList.toggle('ghost', currentEnabled !== false);
  }

  async function refreshDevicePushState() {
    if (!document.getElementById(BUTTON_ID)) return;
    if (!supported()) {
      currentEnabled = null;
      setStatus('Este navegador não oferece Web Push.');
      renderButton();
      return;
    }
    if (!window.isSecureContext) {
      currentEnabled = null;
      setStatus('Use HTTPS ou localhost para controlar notificações neste dispositivo.');
      renderButton();
      return;
    }

    try {
      const subscription = await currentSubscription();
      if (!subscription) {
        currentEnabled = null;
        setStatus('Neste dispositivo: notificações ainda não foram ativadas.');
        renderButton();
        return;
      }

      const params = new URLSearchParams({ endpoint: subscription.endpoint });
      const state = await api(`/api/push/device/state?${params.toString()}`);
      if (!state.registered) {
        currentEnabled = null;
        setStatus('Neste dispositivo: inscrição do navegador existe, mas ainda não está registrada no servidor.');
      } else {
        currentEnabled = Boolean(state.enabled);
        setStatus(currentEnabled
          ? 'Neste dispositivo: notificações ativas.'
          : 'Neste dispositivo: notificações pausadas. Os outros aparelhos continuam recebendo normalmente.',
          currentEnabled ? 'active' : 'paused');
      }
      renderButton();
    } catch (error) {
      currentEnabled = null;
      setStatus(`Não foi possível consultar este dispositivo: ${error.message}`);
      renderButton();
    }
  }

  async function toggleDevicePushPause() {
    if (busy) return;
    const subscription = await currentSubscription().catch(() => null);
    if (!subscription) {
      toast('Ative primeiro as notificações neste dispositivo.', 'error');
      await refreshDevicePushState();
      return;
    }

    busy = true;
    renderButton();
    try {
      const nextEnabled = currentEnabled === false;
      const result = await api('/api/push/device/state', {
        method: 'PATCH',
        body: JSON.stringify({ endpoint: subscription.endpoint, enabled: nextEnabled }),
      });
      currentEnabled = Boolean(result.enabled);
      setStatus(currentEnabled
        ? 'Neste dispositivo: notificações ativas.'
        : 'Neste dispositivo: notificações pausadas. Os outros aparelhos continuam recebendo normalmente.',
        currentEnabled ? 'active' : 'paused');
      toast(currentEnabled
        ? 'Notificações retomadas somente neste dispositivo.'
        : 'Notificações pausadas somente neste dispositivo.');
    } catch (error) {
      toast(`Notificações deste dispositivo: ${error.message}`, 'error');
    } finally {
      busy = false;
      renderButton();
    }
  }

  function installControls() {
    if (document.getElementById(BUTTON_ID)) return true;
    const enable = document.getElementById('enablePushBtn');
    const actions = enable?.closest('.push-actions');
    if (!actions) return false;

    const button = document.createElement('button');
    button.type = 'button';
    button.id = BUTTON_ID;
    button.className = 'button ghost';
    button.textContent = 'Pausar neste dispositivo';
    button.disabled = true;
    button.addEventListener('click', toggleDevicePushPause);
    actions.appendChild(button);

    const status = document.createElement('p');
    status.id = STATUS_ID;
    status.className = 'field-help';
    status.textContent = 'Verificando notificações deste dispositivo…';
    actions.insertAdjacentElement('afterend', status);

    // The existing V4 button creates/re-enables the current subscription. Refresh
    // our device-only state after it finishes without changing that proven flow.
    enable.addEventListener('click', () => {
      [400, 1200, 2500].forEach(delay => setTimeout(refreshDevicePushState, delay));
    });

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refreshDevicePushState();
    });

    refreshDevicePushState();
    return true;
  }

  if (!installControls()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (installControls() || attempts > 40) clearInterval(timer);
    }, 150);
  }
})();
