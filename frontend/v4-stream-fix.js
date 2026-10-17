(() => {
  function sameOriginStreamUrl(camera) {
    return `/go2rtc/stream.html?src=${encodeURIComponent(camera.stream_name)}`;
  }

  function audioViewerUrl(camera, speakerOn, micOn) {
    const params = new URLSearchParams({
      camera_id: String(camera.id),
      listen: speakerOn ? '1' : '0',
      microphone: micOn ? '1' : '0',
    });
    return `/camera-webrtc.html?${params.toString()}`;
  }

  // Keep normal video on go2rtc's universal player. H.265 is not generally
  // negotiable through browser WebRTC, but the universal player can select MSE.
  // Audio/talkback uses a separate page whose WebRTC offer is audio-only.
  viewerMediaUrl = function(camera, speakerOn, micOn) {
    if (!speakerOn && !micOn) return sameOriginStreamUrl(camera);
    return audioViewerUrl(camera, speakerOn, micOn);
  };

  cameraCard = function(camera) {
    const [label, cls] = statusLabel(camera);
    const preview = camera.enabled && camera.sync_status === 'ok'
      ? `<iframe src="${sameOriginStreamUrl(camera)}" title="${escapeHtml(camera.name)}" loading="lazy" allow="autoplay"></iframe><span class="live-badge">LIVE</span>`
      : `<div class="camera-preview disabled"><span>${camera.sync_status === 'error' ? 'Stream indisponível' : 'Câmera desativada'}</span></div>`;
    return `<article class="camera-card" data-id="${camera.id}"><div class="camera-preview">${preview}</div><div class="camera-meta"><div><h3>${escapeHtml(camera.name)}</h3><p>${escapeHtml(camera.location || 'Sem local definido')}</p></div><span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span></div></article>`;
  };

  try { render(); } catch (_) {}
})();
