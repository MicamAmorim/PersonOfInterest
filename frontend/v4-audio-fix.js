(() => {
  const talk = document.getElementById('talkMicBtn');
  if (!talk || typeof state === 'undefined') return;

  let talking = false;
  let resumeSpeaker = false;
  let activePointerId = null;

  const baseUpdateAudioControls = typeof updateAudioControls === 'function'
    ? updateAudioControls
    : null;

  function renderHalfDuplexAudioState() {
    if (baseUpdateAudioControls) baseUpdateAudioControls();
    if (!talking) {
      talk.textContent = '🎙 Segure p/ falar';
      talk.title = 'Segure enquanto fala. O áudio da câmera é silenciado temporariamente para evitar retroalimentação.';
      if (state.viewer?.speakerOn) {
        const status = document.getElementById('audioStatus');
        if (status) status.textContent = 'Áudio da câmera ativo · segure o microfone para falar';
      }
    } else {
      talk.textContent = '🎤 Falando…';
      talk.title = 'Solte para parar de falar';
      const status = document.getElementById('audioStatus');
      if (status) status.textContent = 'Falando para a câmera · escuta suspensa para evitar eco';
    }
  }

  // Override the global renderer so every viewer reload preserves the
  // push-to-talk wording/state introduced here.
  if (baseUpdateAudioControls) updateAudioControls = renderHalfDuplexAudioState;

  function canStartTalk() {
    if (!state.viewer?.cameraId) return false;
    if (!window.isSecureContext) {
      toast('O navegador só libera microfone em HTTPS ou localhost. Para acesso remoto, use HTTPS.', 'error');
      return false;
    }
    if (state.viewer.talkbackConfigured === false) {
      toast('Esta câmera ainda não anunciou/configurou backchannel de áudio.', 'error');
      return false;
    }
    return true;
  }

  function startTalk(event) {
    if (talking || !canStartTalk()) return;
    event?.preventDefault?.();
    event?.stopImmediatePropagation?.();

    talking = true;
    resumeSpeaker = Boolean(state.viewer.speakerOn);
    state.viewer.speakerOn = false;
    state.viewer.micOn = true;

    if (event?.pointerId != null) {
      activePointerId = event.pointerId;
      try { talk.setPointerCapture(event.pointerId); } catch (_) {}
    }

    reloadViewerMedia();
    renderHalfDuplexAudioState();
  }

  function stopTalk(event) {
    if (!talking) return;
    event?.preventDefault?.();
    event?.stopImmediatePropagation?.();

    talking = false;
    state.viewer.micOn = false;
    state.viewer.speakerOn = resumeSpeaker;
    resumeSpeaker = false;

    if (activePointerId != null) {
      try { talk.releasePointerCapture(activePointerId); } catch (_) {}
      activePointerId = null;
    }

    reloadViewerMedia();
    renderHalfDuplexAudioState();
  }

  // The legacy runtime uses click-to-toggle. Capture the click before that
  // handler and replace it with real push-to-talk semantics.
  talk.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  talk.addEventListener('pointerdown', startTalk, true);
  talk.addEventListener('pointerup', stopTalk, true);
  talk.addEventListener('pointercancel', stopTalk, true);
  talk.addEventListener('lostpointercapture', () => stopTalk(), true);
  talk.addEventListener('contextmenu', event => event.preventDefault());

  // Keyboard accessibility: hold Space/Enter just like holding the button.
  talk.addEventListener('keydown', event => {
    if (event.repeat || ![' ', 'Enter'].includes(event.key)) return;
    startTalk(event);
  }, true);
  talk.addEventListener('keyup', event => {
    if (![' ', 'Enter'].includes(event.key)) return;
    stopTalk(event);
  }, true);

  // Never leave the browser microphone transmitting if the tab/view loses focus.
  window.addEventListener('blur', () => stopTalk());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopTalk();
  });

  renderHalfDuplexAudioState();
})();
