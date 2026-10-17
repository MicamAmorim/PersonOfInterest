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
    const result = await api('/api/discovery/probe', {
      method: 'POST',
      body: JSON.stringify({ ip }),
    });
    if (result.ok) {
      state.discovery.verified = { ip, path: result.path, username: '', password: '' };
      $('#saveDiscoveryBtn').disabled = false;
      setProbeResult(`RTSP validado sem credenciais em ${result.path}.`, 'ok');
    } else if (result.auth_required) {
      setProbeResult('A câmera exige usuário e senha. Informe as credenciais do dispositivo e clique em Testar acesso.', 'warning');
      $('#discoveryUsername').focus();
    } else {
      setProbeResult(result.error || 'RTSP encontrado, mas o caminho não pôde ser validado automaticamente.', 'error');
    }
  } catch (error) {
    setProbeResult(error.message, 'error');
  }
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
    const result = await api('/api/discovery/probe', {
      method: 'POST',
      body: JSON.stringify({ ip: device.ip, username, password }),
    });
    if (result.ok) {
      state.discovery.verified = { ip: device.ip, path: result.path, username, password };
      $('#saveDiscoveryBtn').disabled = false;
      setProbeResult(`Acesso validado. Stream encontrado em ${result.path}.`, 'ok');
    } else {
      setProbeResult(result.error || (result.auth_required ? 'Usuário ou senha não aceitos.' : 'Não foi possível validar o stream.'), 'error');
    }
  } catch (error) {
    setProbeResult(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = 'Testar acesso';
  }
}

function rtspUrlFromVerified(verified) {
  const user = verified.username || '';
  const password = verified.password || '';
  const auth = user ? `${encodeURIComponent(user)}:${encodeURIComponent(password)}@` : '';
  return `rtsp://${auth}${verified.ip}:554${verified.path}`;
}

async function saveDiscoveredCamera() {
  const verified = state.discovery.verified;
  if (!verified) return;
  const button = $('#saveDiscoveryBtn');
  button.disabled = true;
  button.textContent = 'Adicionando…';
  try {
    await api('/api/cameras', {
      method: 'POST',
      body: JSON.stringify({
        name: $('#discoveryName').value.trim() || `Câmera ${verified.ip.split('.').pop()}`,
        location: '',
        rtsp_url: rtspUrlFromVerified(verified),
        enabled: true,
      }),
    });
    $('#discoveryPassword').value = '';
    closeDiscovery();
    await Promise.all([loadCameras(), loadHealth()]);
    toast('Câmera descoberta, testada e adicionada.');
  } catch (error) {
    setProbeResult(error.message, 'error');
    button.disabled = false;
  } finally {
    button.textContent = 'Adicionar câmera';
  }
}

function openViewer(id) {
  const camera = state.cameras.find(c => c.id === id);
  if (!camera) return;
  if (!camera.enabled || camera.sync_status !== 'ok') {
    toast(camera.sync_error || 'Esta câmera não está disponível.', 'error');
    return;
  }
  $('#viewerTitle').textContent = camera.name;
  $('#viewerLocation').textContent = camera.location || '';
  $('#viewerFrame').src = resolveViewerUrl(camera.viewer_url);
  $('#viewerDialog').showModal();
}

function closeViewer() {
  $('#viewerFrame').src = 'about:blank';
  $('#viewerDialog').close();
}

$$('.nav-item').forEach(el => el.addEventListener('click', () => setView(el.dataset.view)));
$('#addCameraBtn').addEventListener('click', () => openCameraDialog());
$('#discoverBtn').addEventListener('click', openDiscovery);
$('#emptyDiscoverBtn').addEventListener('click', openDiscovery);
$('#emptyAddBtn').addEventListener('click', () => openCameraDialog());
$('#refreshBtn').addEventListener('click', () => Promise.all([loadCameras(), loadHealth()]));
$('#syncAllBtn').addEventListener('click', syncAll);
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

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(console.warn));
}

Promise.all([loadCameras(), loadHealth()]);
setInterval(loadHealth, 30000);
