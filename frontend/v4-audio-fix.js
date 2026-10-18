(() => {
  const talk = document.getElementById('talkMicBtn');
  if (!talk || typeof state === 'undefined') return;

  let talking = false;
  let resumeSpeaker = false;
  let activePointerId = null;

  const baseUpdateAudioControls = typeof updateAudioControls === 'function'
    ? updateAudioControls
    : null;

  function muteMediaElement(element) {
    try { element.muted = true; } catch (_) {}
    try { element.volume = 0; } catch (_) {}
    if (element.tagName === 'AUDIO') {
      try { element.pause(); } catch (_) {}
    }
  }

  function muteDeep(root) {
    if (!root?.querySelectorAll) return;
    root.querySelectorAll('audio,video').forEach(muteMediaElement);
    root.querySelectorAll('*').forEach(element => {
      try {
        if (element.shadowRoot) muteDeep(element.shadowRoot);
      } catch (_) {}
    });
  }

  function hardMuteCurrentViewer() {
    const frame = document.getElementById('viewerFrame');
    if (!frame) return;

    // Same-origin synchronous mute first: this closes the acoustic loop before
    // the old iframe has time to unload and before the new page asks for mic.
    try {
      const doc = frame.contentDocument;
      muteDeep(doc);
      const remoteAudio = doc?.getElementById('remoteAudio');
      if (remoteAudio) {
        remoteAudio.muted = true;
        remoteAudio.volume = 0;
        try { remoteAudio.pause(); } catch (_) {}
      }
      const nested = doc?.getElementById('videoFrame');
      if (nested?.contentDocument) muteDeep(nested.contentDocument);
    } catch (_) {}

    // Message fallback lets camera-webrtc disable receiver tracks as well.
    try {
      frame.contentWindow?.postMessage({ source: 'personofinterest-parent', type: 'hard-mute-audio' }, location.origin);
    } catch (_) {}
  }

  function renderHalfDuplexAudioState() {
    if (baseUpdateAudioControls) baseUpdateAudioControls();
    if (!talking) {
      talk.textContent = '🎙 Segure p/ falar';
      talk.title = 'Segure enquanto fala. O áudio da câmera é cortado antes de abrir o microfone para evitar retroalimentação.';
      if (state.viewer?.speakerOn) {
        const status = document.getElementById('audioStatus');
        if (status) status.textContent = 'Áudio da câmera ativo · segure o microfone para falar';
      }
    } else {
      talk.textContent = '🎤 Falando…';
      talk.title = 'Solte para parar de falar';
      const status = document.getElementById('audioStatus');
      if (status) status.textContent = 'Falando para a câmera · toda escuta local suspensa';
    }
  }

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

    // Cut every currently playing camera-audio path synchronously, before
    // changing iframe URL / opening getUserMedia. This is the key anti-feedback
    // guarantee for push-to-talk.
    hardMuteCurrentViewer();

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

    // Stop outgoing talkback first. Listening is restored only by loading the
    // non-microphone viewer after micOn has been cleared.
    hardMuteCurrentViewer();
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

  talk.addEventListener('keydown', event => {
    if (event.repeat || ![' ', 'Enter'].includes(event.key)) return;
    startTalk(event);
  }, true);
  talk.addEventListener('keyup', event => {
    if (![' ', 'Enter'].includes(event.key)) return;
    stopTalk(event);
  }, true);

  window.addEventListener('blur', () => stopTalk());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopTalk();
  });

  renderHalfDuplexAudioState();
})();

// V4.8 spatial alerts are intentionally isolated from the proven PTT logic
// above. Load their assets after the existing runtime has created the Alerts UI.
(() => {
  if (!document.querySelector('link[data-poi-spatial]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/v48-spatial.css';
    link.dataset.poiSpatial = '1';
    document.head.appendChild(link);
  }
  if (!document.querySelector('script[data-poi-spatial]')) {
    const script = document.createElement('script');
    script.src = '/v48-spatial-alerts.js';
    script.defer = true;
    script.dataset.poiSpatial = '1';
    document.head.appendChild(script);
  }
})();
