async function openDiscovery() {
  const dialog = $('#discoveryDialog');
  state.discovery = { devices: [], selected: null, verified: null };
  $('#discoverySetup').classList.add('hidden');
  $('#discoveryList').classList.remove('hidden');
  $('#discoveryStatus').textContent = 'Escaneando a sub-rede local por RTSP (:554) e ONVIF (:8899)…';
  $('#discoveryList').innerHTML = '<div class="discovery-status">Isso normalmente leva alguns segundos.</div>';
  dialog.showModal();
  try {
    const result = await api('/api/discovery/scan', { method: 'POST', body: '{}' });
    state.discovery.devices = result.devices || [];
    $('#discoverySubtitle').textContent = `${result.subnet} · host ${result.local_ip}`;
    $('#discoveryStatus').textContent = `${state.discovery.devices.length} dispositivo(s) compatível(is) encontrado(s) em ${(result.elapsed_ms / 1000).toFixed(1)} s.`;
    renderDiscoveryDevices();
  } catch (error) {
    $('#discoveryStatus').textContent = `Falha na descoberta: ${error.message}`;
    $('#discoveryList').innerHTML = '';
  }
}

function closeDiscovery() {
  $('#discoveryPassword').value = '';
  state.discovery.verified = null;
  $('#discoveryDialog').close();
}

async function configureDiscoveredDevice(ip) {
  const device = state.discovery.devices.find(d => d.ip === ip);
  if (!device) return;
  state.discovery.selected = device;
  state.discovery.verified = null;
  $('#discoveryList').classList.add('hidden');
  $('#discoverySetup').classList.remove('hidden');
  $('#discoveryDeviceTitle').textContent = ip;
  $('#discoveryUsername').value = '';
  $('#discoveryPassword').value = '';
  $('#discoveryName').value = `Câmera ${ip.split('.').pop()}`;
  $('#saveDiscoveryBtn').disabled = true;
  setProbeResult('Verificando se o RTSP aceita acesso sem credenciais…', 'warning');
  try {
    const result = await api('/api/discovery/probe', { method: 'POST', body: JSON.stringify({ ip }) });
    if (result.ok) {
      state.discovery.verified = { ip, path: result.path, username: '', password: '' };
      $('#saveDiscoveryBtn').disabled = false;
      setProbeResult(`RTSP validado sem credenciais em ${result.path}.`, 'ok');
    } else if (result.auth_required) {
      setProbeResult('A câmera exige usuário e senha. Informe as credenciais e clique em Testar acesso.', 'warning');
      $('#discoveryUsername').focus();
    } else setProbeResult(result.error || 'RTSP encontrado, mas o caminho não pôde ser validado.', 'error');
  } catch (error) { setProbeResult(error.message, 'error'); }
}

function backToDiscovery() {
  $('#discoveryPassword').value = '';
  state.discovery.selected = null;
  state.discovery.verified = null;
  $('#discoverySetup').classList.add('hidden');
  $('#discoveryList').classList.remove('hidden');
}

async function testDiscoveredAccess() {
  const device = state.discovery.selected;
  if (!device) return;
  const username = $('#discoveryUsername').value.trim();
  const password = $('#discoveryPassword').value;
  const button = $('#testDiscoveryBtn');
  resetDiscoveryVerification();
  setProbeResult('Testando autenticação e stream RTSP…', 'warning');
  button.disabled = true;
  button.textContent = 'Testando…';
  try {
    const result = await api('/api/discovery/probe', { method: 'POST', body: JSON.stringify({ ip: device.ip, username, password }) });
    if (result.ok) {
      state.discovery.verified = { ip: device.ip, path: result.path, username, password };
      $('#saveDiscoveryBtn').disabled = false;
      setProbeResult(`Acesso validado. Stream encontrado em ${result.path}.`, 'ok');
    } else setProbeResult(result.error || (result.auth_required ? 'Usuário ou senha não aceitos.' : 'Não foi possível validar o stream.'), 'error');
  } catch (error) { setProbeResult(error.message, 'error'); }
  finally { button.disabled = false; button.textContent = 'Testar acesso'; }
}

function rtspUrlFromVerified(verified) {
  const auth = verified.username ? `${encodeURIComponent(verified.username)}:${encodeURIComponent(verified.password || '')}@` : '';
  return `rtsp://${auth}${verified.ip}:554${verified.path}`;
}

async function saveDiscoveredCamera() {
  const verified = state.discovery.verified;
  if (!verified) return;
  const button = $('#saveDiscoveryBtn');
  button.disabled = true;
  button.textContent = 'Adicionando…';
  try {
    await api('/api/cameras', { method: 'POST', body: JSON.stringify({ name: $('#discoveryName').value.trim() || `Câmera ${verified.ip.split('.').pop()}`, location: '', rtsp_url: rtspUrlFromVerified(verified), enabled: true }) });
    $('#discoveryPassword').value = '';
    closeDiscovery();
    await Promise.all([loadCameras(), loadHealth()]);
    toast('Câmera descoberta, testada e adicionada.');
  } catch (error) {
    setProbeResult(error.message, 'error');
    button.disabled = false;
  } finally { button.textContent = 'Adicionar câmera'; }
}

function renderVisionOverlay(vision) {
  const overlay = $('#visionOverlay');
  if (!overlay) return;
  const tracks = vision.tracks || [];
  overlay.innerHTML = tracks.map(track => {
    const b = track.bbox;
    const selected = Number(track.track_id) === Number(state.viewer.selectedTrackId);
    const stable = track.control_valid !== false;
    const cls = `${selected ? 'selected' : ''} ${track.has_face ? 'face' : ''} ${stable ? '' : 'unstable'} ${track.face_search ? 'face-search' : ''}`;
    let suffix = stable ? '' : ' · aguardando';
    if (track.face_search) suffix += ' · procurando rosto';
    return `<button class="track-box ${cls}" title="${escapeHtml(track.control_reason || '')}" data-track-id="${track.track_id}" style="left:${b.x * 100}%;top:${b.y * 100}%;width:${b.w * 100}%;height:${b.h * 100}%"><span>#${track.track_id}${track.has_face ? ' · face' : ''}${suffix}</span></button>`;
  }).join('');
  $$('[data-track-id]').forEach(el => el.addEventListener('click', async (event) => {
    event.stopPropagation();
    state.viewer.selectedTrackId = Number(el.dataset.trackId);
    $('#trackHint').textContent = `Pessoa #${state.viewer.selectedTrackId} selecionada.`;
    if ($('#autoFollowToggle').checked) await setAutoFollow(true);
    renderVisionOverlay(vision);
  }));
}

function syncFollowSpeedControl(value) {
  const slider = $('#followMaxSpeed');
  if (!slider) return;
  const percent = Math.round(Number(value || 0.65) * 100);
  if (document.activeElement !== slider) slider.value = String(percent);
  $('#followMaxSpeedValue').textContent = `${slider.value}%`;
}

async function pollVision() {
  const cameraId = state.viewer.cameraId;
  if (!cameraId || !$('#viewerDialog').open) return;
  try {
    const vision = await api(`/api/vision/cameras/${cameraId}/state`);
    renderVisionOverlay(vision);
    const count = (vision.tracks || []).length;
    const status = vision.status === 'running' ? `${count} pessoa(s)` : vision.status;
    const latency = vision.capture_latency_ms != null && vision.status === 'running' ? ` · fila ${Math.round(vision.capture_latency_ms)} ms` : '';
    $('#visionStatus').textContent = `Visão: ${status}${latency}${vision.error ? ` · ${vision.error}` : ''}`;
    $('#autoFollowToggle').checked = Boolean(vision.auto_follow_enabled);
    if (vision.selected_track_id && !state.viewer.selectedTrackId) state.viewer.selectedTrackId = vision.selected_track_id;
    $('#homeStatus').textContent = vision.home_preset_set ? 'Home definido' : 'Home não definido';
    syncFollowSpeedControl(vision.autofollow_max_speed);
    if (vision.auto_follow_enabled && vision.target_lost_seconds > 0) {
      $('#trackHint').textContent = vision.target_lost_seconds >= 3
        ? 'Alvo perdido: retornando à posição Home.'
        : `Alvo temporariamente perdido (${vision.target_lost_seconds.toFixed(1)} s / 3 s).`;
    }
    if (vision.ptz_error) $('#ptzStatus').textContent = `PTZ: ${vision.ptz_error}`;
  } catch (error) {
    $('#visionStatus').textContent = `Visão: ${error.message}`;
  }
}

async function setAutoFollow(enabled) {
  const cameraId = state.viewer.cameraId;
  if (!cameraId) return;
  try {
    await api(`/api/vision/cameras/${cameraId}/follow`, { method: 'POST', body: JSON.stringify({ enabled, track_id: enabled ? state.viewer.selectedTrackId : null }) });
    $('#autoFollowToggle').checked = enabled;
    $('#trackHint').textContent = enabled
      ? (state.viewer.selectedTrackId ? `Acompanhando pessoa #${state.viewer.selectedTrackId}.` : 'Auto-follow ativo: será usada a pessoa mais destacada até você selecionar outra.')
      : 'Clique numa caixa de pessoa para selecioná-la para acompanhamento.';
  } catch (error) {
    $('#autoFollowToggle').checked = false;
    toast(`Auto-follow: ${error.message}`, 'error');
  }
}

async function saveFollowMaxSpeed() {
  const cameraId = state.viewer.cameraId;
  if (!cameraId) return;
  const slider = $('#followMaxSpeed');
  const percent = Number(slider.value);
  $('#followMaxSpeedValue').textContent = `${percent}%`;
  try {
    const result = await api(`/api/vision/cameras/${cameraId}/settings`, {
      method: 'PATCH',
      body: JSON.stringify({ autofollow_max_speed: percent / 100 }),
    });
    syncFollowSpeedControl(result.autofollow_max_speed);
    toast(`Velocidade máxima do auto-follow: ${Math.round(result.autofollow_max_speed * 100)}%.`);
  } catch (error) {
    toast(`Velocidade do auto-follow: ${error.message}`, 'error');
    await pollVision();
  }
}

function viewerMediaUrl(camera, speakerOn, micOn) {
  // Preserve go2rtc's stream.html fallback (WebRTC/MSE/MP4/MJPEG) while both
  // audio directions are off. Switch to our WebRTC player only on explicit user
  // activation so camera audio is guaranteed muted by default.
  if (!speakerOn && !micOn) return resolveViewerUrl(camera.viewer_url);
  const params = new URLSearchParams({
    src: camera.stream_name,
    listen: speakerOn ? '1' : '0',
    microphone: micOn ? '1' : '0',
    rtc_port: '1984',
  });
  return `/camera-webrtc.html?${params.toString()}`;
}

function updateAudioControls() {
  const listen = $('#listenAudioBtn');
  const talk = $('#talkMicBtn');
  listen.setAttribute('aria-pressed', String(state.viewer.speakerOn));
  talk.setAttribute('aria-pressed', String(state.viewer.micOn));
  listen.classList.toggle('active', state.viewer.speakerOn);
  talk.classList.toggle('active', state.viewer.micOn);
  listen.textContent = state.viewer.speakerOn ? '🔊 Áudio' : '🔇 Áudio';
  talk.textContent = state.viewer.micOn ? '🎤 Falando' : '🎙 Microfone';
  const status = state.viewer.micOn
    ? (state.viewer.speakerOn ? 'Áudio ativo · microfone transmitindo' : 'Microfone transmitindo · áudio local mutado')
    : (state.viewer.speakerOn ? 'Áudio da câmera ativo · microfone mutado' : 'Áudio e microfone mutados');
  $('#audioStatus').textContent = status;
}

function reloadViewerMedia() {
  const camera = state.cameras.find(c => c.id === state.viewer.cameraId);
  if (!camera) return;
  $('#viewerFrame').src = viewerMediaUrl(camera, state.viewer.speakerOn, state.viewer.micOn);
  updateAudioControls();
}

async function checkAudio(cameraId) {
  state.viewer.talkbackConfigured = false;
  try {
    const result = await api(`/api/cameras/${cameraId}/audio/status`);
    state.viewer.talkbackConfigured = Boolean(result.talkback_configured);
    $('#talkMicBtn').disabled = !result.talkback_configured;
    $('#listenAudioBtn').disabled = !result.ok;
    if (!result.talkback_configured) $('#talkMicBtn').title = 'Backchannel não detectado/configurado para esta câmera';
  } catch (_) {
    $('#talkMicBtn').disabled = false;
  }
}

function toggleCameraAudio() {
  state.viewer.speakerOn = !state.viewer.speakerOn;
  reloadViewerMedia();
}

function toggleCameraMicrophone() {
  if (!state.viewer.micOn && !window.isSecureContext) {
    toast('O navegador só libera microfone em HTTPS ou localhost. Para acesso remoto, use HTTPS.', 'error');
    return;
  }
  if (!state.viewer.micOn && state.viewer.talkbackConfigured === false) {
    toast('Esta câmera ainda não anunciou/configurou backchannel de áudio.', 'error');
    return;
  }
  state.viewer.micOn = !state.viewer.micOn;
  reloadViewerMedia();
  if (state.viewer.micOn) toast('Autorize o microfone no navegador se ele solicitar permissão.');
}

window.addEventListener('message', (event) => {
  if (event.origin !== location.origin || event.data?.source !== 'personofinterest-camera-webrtc') return;
  const type = event.data.type || '';
  if (['webrtc-error', 'signal-error', 'connection-error', 'autoplay-blocked'].includes(type)) {
    $('#audioStatus').textContent = event.data.message || 'Falha no áudio WebRTC';
    if (type !== 'autoplay-blocked') toast(event.data.message || 'Falha no áudio WebRTC', 'error');
  }
});

async function checkPTZ(cameraId) {
  state.viewer.ptzReady = false;
  $('#ptzStatus').textContent = 'PTZ: verificando…';
  try {
    const result = await api(`/api/cameras/${cameraId}/ptz/status`);
    state.viewer.ptzReady = Boolean(result.ok);
    const protocol = result.protocol ? result.protocol.toUpperCase() : 'PTZ';
    $('#ptzStatus').textContent = result.ok ? `PTZ: ${protocol} pronto` : `PTZ: ${result.error || 'indisponível'}`;
    $('#homeStatus').textContent = result.home_preset_set ? 'Home definido' : 'Home não definido';
    syncFollowSpeedControl(result.autofollow_max_speed);
    $('#ptzJoystick').classList.toggle('unavailable', !result.ok);
    $('#setHomeBtn').disabled = !result.ok;
    $('#gotoHomeBtn').disabled = !result.ok || !result.home_preset_set;
    $('#followMaxSpeed').disabled = !result.ok;
  } catch (error) {
    $('#ptzStatus').textContent = `PTZ: ${error.message}`;
    $('#ptzJoystick').classList.add('unavailable');
    $('#followMaxSpeed').disabled = true;
  }
}

async function setHomePosition() {
  const cameraId = state.viewer.cameraId;
  if (!cameraId) return;
  if (!confirm('Usar a posição atual da câmera como posição inicial (Home)?')) return;
  try {
    await api(`/api/cameras/${cameraId}/ptz/home/set`, { method: 'POST', body: '{}' });
    $('#homeStatus').textContent = 'Home definido';
    $('#gotoHomeBtn').disabled = false;
    toast('Posição inicial salva na câmera.');
  } catch (error) { toast(`Home: ${error.message}`, 'error'); }
}

async function gotoHomePosition() {
  const cameraId = state.viewer.cameraId;
  if (!cameraId) return;
  try {
    if ($('#autoFollowToggle').checked) await setAutoFollow(false);
    await api(`/api/cameras/${cameraId}/ptz/home/goto`, { method: 'POST', body: '{}' });
    toast('Retornando à posição inicial.');
  } catch (error) { toast(`Home: ${error.message}`, 'error'); }
}

function openViewer(id) {
  const camera = state.cameras.find(c => c.id === id);
  if (!camera) return;
  if (!camera.enabled || camera.sync_status !== 'ok') { toast(camera.sync_error || 'Esta câmera não está disponível.', 'error'); return; }
  state.viewer.cameraId = id;
  state.viewer.selectedTrackId = null;
  state.viewer.speakerOn = false;
  state.viewer.micOn = false;
  state.viewer.talkbackConfigured = null;
  $('#viewerTitle').textContent = camera.name;
  $('#viewerLocation').textContent = camera.location || '';
  $('#viewerFrame').src = viewerMediaUrl(camera, false, false);
  updateAudioControls();
  $('#listenAudioBtn').disabled = false;
  $('#talkMicBtn').disabled = false;
  $('#visionOverlay').innerHTML = '';
  $('#visionStatus').textContent = 'Visão: iniciando…';
  $('#autoFollowToggle').checked = false;
  $('#followMaxSpeed').disabled = true;
  $('#viewerDialog').showModal();
  pollVision();
  clearInterval(state.viewer.pollTimer);
  state.viewer.pollTimer = setInterval(pollVision, 500);
  checkPTZ(id);
  setTimeout(() => checkAudio(id), 400);
}

async function closeViewer() {
  clearInterval(state.viewer.pollTimer);
  state.viewer.pollTimer = null;
  if (state.viewer.cameraId) {
    try { await api(`/api/cameras/${state.viewer.cameraId}/ptz/stop`, { method: 'POST', body: '{}' }); } catch (_) {}
  }
  state.viewer.speakerOn = false;
  state.viewer.micOn = false;
  updateAudioControls();
  $('#viewerFrame').src = 'about:blank';
  $('#visionOverlay').innerHTML = '';
  state.viewer.cameraId = null;
  state.viewer.selectedTrackId = null;
  $('#viewerDialog').close();
}

let joystickActive = false;
let joystickLastSend = 0;
function joystickVector(event) {
  const ring = $('#ptzJoystick').getBoundingClientRect();
  const cx = ring.left + ring.width / 2;
  const cy = ring.top + ring.height / 2;
  let dx = (event.clientX - cx) / (ring.width / 2);
  let dy = (event.clientY - cy) / (ring.height / 2);
  const mag = Math.hypot(dx, dy);
  if (mag > 1) { dx /= mag; dy /= mag; }
  return { pan: dx, tilt: -dy, visualX: dx, visualY: dy, mag: Math.min(1, mag) };
}

async function sendJoystick(event) {
  if (!joystickActive || !state.viewer.cameraId || !state.viewer.ptzReady) return;
  const v = joystickVector(event);
  $('#ptzKnob').style.transform = `translate(${v.visualX * 30}px, ${v.visualY * 30}px)`;
  const now = performance.now();
  if (now - joystickLastSend < 150 || v.mag < 0.15) return;
  joystickLastSend = now;
  try {
    await api(`/api/cameras/${state.viewer.cameraId}/ptz/move`, { method: 'POST', body: JSON.stringify({ pan: v.pan, tilt: v.tilt, speed: Math.max(.22, v.mag * .58), duration: .20 }) });
  } catch (error) { $('#ptzStatus').textContent = `PTZ: ${error.message}`; }
}

async function endJoystick() {
  if (!joystickActive) return;
  joystickActive = false;
  $('#ptzKnob').style.transform = 'translate(0, 0)';
  if (state.viewer.cameraId) {
    try { await api(`/api/cameras/${state.viewer.cameraId}/ptz/stop`, { method: 'POST', body: '{}' }); } catch (_) {}
  }
}

$$('.nav-item').forEach(el => el.addEventListener('click', () => setView(el.dataset.view)));
$('#addCameraBtn').addEventListener('click', () => openCameraDialog());
$('#discoverBtn').addEventListener('click', openDiscovery);
$('#emptyDiscoverBtn').addEventListener('click', openDiscovery);
$('#emptyAddBtn').addEventListener('click', () => openCameraDialog());
$('#refreshBtn').addEventListener('click', () => Promise.all([loadCameras(), loadHealth(), loadEvents(), loadPersons()]));
$('#syncAllBtn').addEventListener('click', syncAll);
$('#timelineRefresh').addEventListener('click', loadEvents);
$('#timelineDeleteAll').addEventListener('click', deleteAllTimelineEvents);
$('#timelineDeleteSelected').addEventListener('click', deleteSelectedTimelineEvents);
$('#timelineSelectAll').addEventListener('click', toggleSelectAllTimelineEvents);
$('#timelineClearFilters').addEventListener('click', clearTimelineFilters);
$('#timelineCamera').addEventListener('change', loadEvents);
$('#timelinePerson').addEventListener('change', loadEvents);
$('#timelineFace').addEventListener('change', loadEvents);
$('#cameraForm').addEventListener('submit', saveCamera);
$('#backToDiscoveryBtn').addEventListener('click', backToDiscovery);
$('#testDiscoveryBtn').addEventListener('click', testDiscoveredAccess);
$('#saveDiscoveryBtn').addEventListener('click', saveDiscoveredCamera);
$('[data-discovery-close]').addEventListener('click', closeDiscovery);
$('#discoveryDialog').addEventListener('cancel', (event) => { event.preventDefault(); closeDiscovery(); });
$('#discoveryUsername').addEventListener('input', resetDiscoveryVerification);
$('#discoveryPassword').addEventListener('input', resetDiscoveryVerification);
$$('[data-close]').forEach(el => el.addEventListener('click', () => $('#cameraDialog').close()));
$('[data-viewer-close]').addEventListener('click', closeViewer);
$('#viewerDialog').addEventListener('cancel', (event) => { event.preventDefault(); closeViewer(); });
$('#autoFollowToggle').addEventListener('change', (event) => setAutoFollow(event.target.checked));
$('#listenAudioBtn').addEventListener('click', toggleCameraAudio);
$('#talkMicBtn').addEventListener('click', toggleCameraMicrophone);
$('#setHomeBtn').addEventListener('click', setHomePosition);
$('#gotoHomeBtn').addEventListener('click', gotoHomePosition);
$('#followMaxSpeed').addEventListener('input', (event) => { $('#followMaxSpeedValue').textContent = `${event.target.value}%`; });
$('#followMaxSpeed').addEventListener('change', saveFollowMaxSpeed);

$('#ptzJoystick').addEventListener('pointerdown', async (event) => {
  if (!state.viewer.ptzReady) return;
  if ($('#autoFollowToggle').checked) await setAutoFollow(false);
  joystickActive = true;
  $('#ptzJoystick').setPointerCapture(event.pointerId);
  sendJoystick(event);
});
$('#ptzJoystick').addEventListener('pointermove', sendJoystick);
$('#ptzJoystick').addEventListener('pointerup', endJoystick);
$('#ptzJoystick').addEventListener('pointercancel', endJoystick);

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(console.warn));

Promise.all([loadCameras(), loadHealth(), loadEvents(), loadPersons()]);
setInterval(loadHealth, 30000);
