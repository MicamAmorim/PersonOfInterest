const state = { cameras: [], view: 'dashboard', discovery: { devices: [], selected: null, verified: null } };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}


function resolveViewerUrl(raw) {
  const prefix = '/__go2rtc_direct__/';
  if (!raw || !raw.startsWith(prefix)) return raw;
  const path = raw.slice(prefix.length);
  return `http://${window.location.hostname}:1984/${path}`;
}

function toast(message, type = 'ok') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast show ${type === 'error' ? 'error' : ''}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.className = 'toast'; }, 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join('; ') : data.detail;
    throw new Error(detail || `Erro HTTP ${response.status}`);
  }
  return data;
}

async function loadHealth() {
  try {
    const health = await api('/api/health');
    const ok = health.database === 'ok' && health.go2rtc === 'ok';
    $('#systemDot').className = `status-dot ${ok ? 'ok' : 'error'}`;
    $('#systemStatus').textContent = ok ? 'Sistema online' : 'Atenção';
    $('#systemDetail').textContent = `API ${health.version} · go2rtc ${health.go2rtc}`;
  } catch (error) {
    $('#systemDot').className = 'status-dot error';
    $('#systemStatus').textContent = 'Backend indisponível';
    $('#systemDetail').textContent = error.message;
  }
}

async function loadCameras() {
  try {
    state.cameras = await api('/api/cameras');
    render();
  } catch (error) {
    toast(`Não foi possível carregar as câmeras: ${error.message}`, 'error');
  }
}

function statusLabel(camera) {
  if (!camera.enabled) return ['Desativada', 'disabled'];
  if (camera.sync_status === 'ok') return ['Online', ''];
  if (camera.sync_status === 'error') return ['Erro', 'error'];
  return ['Sincronizando', 'pending'];
}

function render() {
  const active = state.cameras.filter(c => c.enabled).length;
  const synced = state.cameras.filter(c => c.enabled && c.sync_status === 'ok').length;
  $('#cameraCount').textContent = state.cameras.length;
  $('#activeCount').textContent = active;
  $('#syncedCount').textContent = synced;

  $('#emptyState').classList.toggle('hidden', state.cameras.length !== 0);
  $('#cameraGrid').innerHTML = state.cameras.map(cameraCard).join('');
  $('#cameraTableBody').innerHTML = state.cameras.map(cameraRow).join('') || '<tr><td colspan="5" class="muted">Nenhuma câmera cadastrada.</td></tr>';

  $$('.camera-card').forEach(el => el.addEventListener('click', () => openViewer(Number(el.dataset.id))));
  $$('[data-edit]').forEach(el => el.addEventListener('click', (e) => { e.stopPropagation(); openCameraDialog(Number(el.dataset.edit)); }));
  $$('[data-delete]').forEach(el => el.addEventListener('click', (e) => { e.stopPropagation(); deleteCamera(Number(el.dataset.delete)); }));
  $$('[data-sync]').forEach(el => el.addEventListener('click', (e) => { e.stopPropagation(); syncCamera(Number(el.dataset.sync)); }));
}

function cameraCard(camera) {
  const [label, cls] = statusLabel(camera);
  const preview = camera.enabled && camera.sync_status === 'ok'
    ? `<iframe src="${resolveViewerUrl(camera.viewer_url)}" title="${escapeHtml(camera.name)}" loading="lazy" allow="autoplay"></iframe><span class="live-badge">LIVE</span>`
    : `<div class="camera-preview disabled"><span>${camera.sync_status === 'error' ? 'Stream indisponível' : 'Câmera desativada'}</span></div>`;
  return `
    <article class="camera-card" data-id="${camera.id}">
      <div class="camera-preview">${preview}</div>
      <div class="camera-meta">
        <div><h3>${escapeHtml(camera.name)}</h3><p>${escapeHtml(camera.location || 'Sem local definido')}</p></div>
        <span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span>
      </div>
    </article>`;
}

function cameraRow(camera) {
  const [label, cls] = statusLabel(camera);
  return `<tr>
    <td><strong>${escapeHtml(camera.name)}</strong></td>
    <td>${escapeHtml(camera.location || '—')}</td>
    <td><code>${escapeHtml(camera.rtsp_url_display)}</code></td>
    <td><span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span></td>
    <td><div class="table-actions">
      <button class="button ghost small" data-sync="${camera.id}">↻</button>
      <button class="button ghost small" data-edit="${camera.id}">Editar</button>
      <button class="button danger small" data-delete="${camera.id}">Excluir</button>
    </div></td>
  </tr>`;
}

function setView(view) {
  state.view = view;
  const titles = { dashboard: 'Visão geral', cameras: 'Câmeras', settings: 'Sistema' };
  $('#pageTitle').textContent = titles[view];
  $$('.view').forEach(el => el.classList.remove('active'));
  $(`#${view}View`).classList.add('active');
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
}

function openCameraDialog(cameraId = null) {
  const camera = state.cameras.find(c => c.id === cameraId);
  $('#cameraId').value = camera?.id || '';
  $('#cameraDialogTitle').textContent = camera ? 'Editar câmera' : 'Nova câmera';
  $('#cameraName').value = camera?.name || '';
  $('#cameraLocation').value = camera?.location || '';
  $('#cameraRtsp').value = '';
  $('#cameraRtsp').required = !camera;
  $('#cameraRtsp').placeholder = camera ? 'Deixe vazio para manter a URL atual' : 'rtsp://usuario:senha@192.168.1.50:554/stream';
  $('#rtspHelp').textContent = camera
    ? `Atual: ${camera.rtsp_url_display}. Deixe vazio para manter a URL atual.`
    : 'A URL será armazenada apenas no SQLite local e enviada internamente ao go2rtc.';
  $('#cameraEnabled').checked = camera ? camera.enabled : true;
  $('#formError').classList.add('hidden');
  $('#cameraDialog').showModal();
}

async function saveCamera(event) {
  event.preventDefault();
  const id = Number($('#cameraId').value) || null;
  const payload = {
    name: $('#cameraName').value.trim(),
    location: $('#cameraLocation').value.trim(),
    enabled: $('#cameraEnabled').checked,
  };
  const rtsp = $('#cameraRtsp').value.trim();
  if (rtsp) payload.rtsp_url = rtsp;
  const save = $('#saveCameraBtn');
  save.disabled = true;
  save.textContent = 'Salvando…';
  try {
    await api(id ? `/api/cameras/${id}` : '/api/cameras', {
      method: id ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    $('#cameraDialog').close();
    toast(id ? 'Câmera atualizada.' : 'Câmera adicionada.');
    await Promise.all([loadCameras(), loadHealth()]);
  } catch (error) {
    $('#formError').textContent = error.message;
    $('#formError').classList.remove('hidden');
  } finally {
    save.disabled = false;
    save.textContent = 'Salvar câmera';
  }
}

async function deleteCamera(id) {
  const camera = state.cameras.find(c => c.id === id);
  if (!camera || !confirm(`Excluir a câmera “${camera.name}”?`)) return;
  try {
    await api(`/api/cameras/${id}`, { method: 'DELETE' });
    toast('Câmera excluída.');
    await loadCameras();
  } catch (error) { toast(error.message, 'error'); }
}

async function syncCamera(id) {
  try {
    toast('Sincronizando stream…');
    await api(`/api/cameras/${id}/sync`, { method: 'POST' });
    await Promise.all([loadCameras(), loadHealth()]);
  } catch (error) { toast(error.message, 'error'); }
}

async function syncAll() {
  try {
    toast('Sincronizando todas as câmeras…');
    await api('/api/cameras/sync-all', { method: 'POST' });
    await Promise.all([loadCameras(), loadHealth()]);
    toast('Sincronização concluída.');
  } catch (error) { toast(error.message, 'error'); }
}


function setProbeResult(message, type = 'ok') {
  const el = $('#discoveryProbeResult');
  el.textContent = message;
  el.className = `probe-result ${type === 'ok' ? '' : type}`.trim();
}

function resetDiscoveryVerification() {
  state.discovery.verified = null;
  $('#saveDiscoveryBtn').disabled = true;
  $('#discoveryProbeResult').classList.add('hidden');
}

function renderDiscoveryDevices() {
  const devices = state.discovery.devices;
  const list = $('#discoveryList');
  if (!devices.length) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">⌁</div><h3>Nenhuma câmera RTSP/ONVIF encontrada</h3><p>Confirme se as câmeras estão ligadas e na mesma rede local deste computador.</p></div>';
    return;
  }
  list.innerHTML = devices.map(device => `
    <article class="discovery-device">
      <div class="discovery-device-main">
        <h3>${escapeHtml(device.ip)}</h3>
        <p>Portas abertas: ${device.open_ports.join(', ')}</p>
        <div class="discovery-badges">
          ${device.rtsp ? '<span class="discovery-badge">RTSP :554</span>' : ''}
          ${device.onvif ? '<span class="discovery-badge onvif">ONVIF :8899</span>' : ''}
          ${device.already_added ? '<span class="discovery-badge added">Já cadastrada</span>' : ''}
        </div>
      </div>
      <button class="button ${device.already_added ? 'ghost' : 'primary'} small" data-configure-device="${escapeHtml(device.ip)}" ${device.already_added ? 'disabled' : ''}>
        ${device.already_added ? 'Cadastrada' : 'Configurar'}
      </button>
    </article>`).join('');
  $$('[data-configure-device]').forEach(el => el.addEventListener('click', () => configureDiscoveredDevice(el.dataset.configureDevice)));
}

