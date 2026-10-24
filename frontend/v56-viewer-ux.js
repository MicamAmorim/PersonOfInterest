(() => {
  if (window.__poiViewerUx56Loaded) return;
  window.__poiViewerUx56Loaded = true;

  const dialog = document.getElementById('viewerDialog');
  const actions = dialog?.querySelector('.viewer-actions');
  const talk = document.getElementById('talkMicBtn');
  const listen = document.getElementById('listenAudioBtn');
  const closeButton = dialog?.querySelector('[data-viewer-close]');
  if (!dialog || !actions || !talk || !listen) return;

  const originalTalkParent = talk.parentElement;
  const originalTalkNext = talk.nextSibling;
  const coarsePointer = window.matchMedia('(pointer: coarse)');
  const compactWidth = window.matchMedia('(max-width: 900px)');
  let fauxFullscreen = false;
  let orientationLocked = false;

  const dock = document.createElement('div');
  dock.id = 'viewerMobileTalkDock';
  dock.className = 'viewer-mobile-talk-dock';
  dock.setAttribute('aria-label', 'Falar pela câmera');
  dialog.appendChild(dock);

  const fullscreenButton = document.createElement('button');
  fullscreenButton.type = 'button';
  fullscreenButton.id = 'viewerFullscreenBtn';
  fullscreenButton.className = 'button ghost small viewer-fullscreen-button';
  fullscreenButton.setAttribute('aria-pressed', 'false');
  fullscreenButton.title = 'Abrir a câmera em tela cheia';
  fullscreenButton.innerHTML = '<span aria-hidden="true">⛶</span> <span class="viewer-fullscreen-label">Tela cheia</span>';
  actions.insertBefore(fullscreenButton, closeButton || null);

  function isMobileLike() {
    return coarsePointer.matches || compactWidth.matches;
  }

  function relocateTalkButton() {
    if (isMobileLike()) {
      if (talk.parentElement !== dock) dock.appendChild(talk);
      talk.classList.add('poi-ptt-large');
      talk.setAttribute('aria-label', 'Segure para falar pela câmera');
    } else {
      if (talk.parentElement === dock && originalTalkParent) {
        if (originalTalkNext && originalTalkNext.parentNode === originalTalkParent) {
          originalTalkParent.insertBefore(talk, originalTalkNext);
        } else {
          originalTalkParent.insertBefore(talk, listen.nextSibling);
        }
      }
      talk.classList.remove('poi-ptt-large');
    }
  }

  function activeFullscreen() {
    return Boolean(document.fullscreenElement || fauxFullscreen);
  }

  function syncFullscreenUi() {
    const active = activeFullscreen();
    dialog.classList.toggle('poi-viewer-fullscreen-active', active);
    document.body.classList.toggle('poi-viewer-fullscreen-body', active);
    fullscreenButton.setAttribute('aria-pressed', active ? 'true' : 'false');
    fullscreenButton.title = active ? 'Sair da tela cheia' : 'Abrir a câmera em tela cheia';
    fullscreenButton.querySelector('.viewer-fullscreen-label').textContent = active ? 'Sair' : 'Tela cheia';
    fullscreenButton.querySelector('span[aria-hidden="true"]').textContent = active ? '↙' : '⛶';
    relocateTalkButton();
  }

  async function tryLandscapeLock() {
    if (!isMobileLike()) return;
    try {
      if (screen.orientation?.lock) {
        await screen.orientation.lock('landscape');
        orientationLocked = true;
        return;
      }
    } catch (_) {
      // Orientation lock is browser/platform controlled (notably restricted on iOS).
    }
    if (typeof toast === 'function' && window.matchMedia('(orientation: portrait)').matches) {
      toast('Tela cheia ativa. Se o aparelho não girar sozinho, gire-o para a horizontal.');
    }
  }

  function unlockOrientation() {
    if (!orientationLocked) return;
    try { screen.orientation?.unlock?.(); } catch (_) {}
    orientationLocked = false;
  }

  function enableFauxFullscreen() {
    fauxFullscreen = true;
    dialog.classList.add('poi-faux-fullscreen');
    syncFullscreenUi();
  }

  async function enterFullscreen() {
    if (activeFullscreen()) return;
    let enteredNative = false;
    try {
      if (dialog.requestFullscreen) {
        await dialog.requestFullscreen({ navigationUI: 'hide' });
        enteredNative = true;
      } else if (dialog.webkitRequestFullscreen) {
        await dialog.webkitRequestFullscreen();
        enteredNative = true;
      }
    } catch (_) {
      enteredNative = false;
    }

    if (!enteredNative) enableFauxFullscreen();
    syncFullscreenUi();
    await tryLandscapeLock();
  }

  async function exitFullscreen() {
    unlockOrientation();
    if (document.fullscreenElement) {
      try { await document.exitFullscreen(); } catch (_) {}
    }
    fauxFullscreen = false;
    dialog.classList.remove('poi-faux-fullscreen');
    syncFullscreenUi();
  }

  async function toggleFullscreen() {
    if (activeFullscreen()) await exitFullscreen();
    else await enterFullscreen();
  }

  fullscreenButton.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    toggleFullscreen();
  });

  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement) {
      fauxFullscreen = false;
      dialog.classList.remove('poi-faux-fullscreen');
      unlockOrientation();
    }
    syncFullscreenUi();
  });

  document.addEventListener('webkitfullscreenchange', syncFullscreenUi);

  closeButton?.addEventListener('click', () => {
    if (activeFullscreen()) exitFullscreen();
  }, true);

  dialog.addEventListener('close', () => {
    if (activeFullscreen()) exitFullscreen();
  });

  window.addEventListener('pagehide', unlockOrientation);
  window.addEventListener('resize', relocateTalkButton, { passive: true });
  try {
    coarsePointer.addEventListener?.('change', relocateTalkButton);
    compactWidth.addEventListener?.('change', relocateTalkButton);
  } catch (_) {}

  // The native PTT listener remains on the exact same #talkMicBtn element. Moving
  // that element changes only layout; its half-duplex/talkback safety handlers stay intact.
  relocateTalkButton();
  syncFullscreenUi();
})();
