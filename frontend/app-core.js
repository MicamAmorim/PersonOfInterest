const state = {
  cameras: [],
  events: [],
  persons: [],
  selectedEventIds: new Set(),
  view: 'dashboard',
  discovery: { devices: [], selected: null, verified: null },
  viewer: {
    cameraId: null,
    selectedTrackId: null,
    pollTimer: null,
    ptzReady: false,
    speakerOn: false,
    micOn: false,
  },
};

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

function go2rtcBase() {
  return `http://${window.location.hostname}:1984`;
}

function toast(message, type = 'ok') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast show ${type === 'error' ? 'error' : ''}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.className = 'toast'; }, 2800);
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
    $('#systemDetail').textContent = `API ${health.version} · go2rtc ${health.go2rtc} · visão ${health.vision}`;
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

async function loadPersons() {
  try {
    state.persons = await api('/api/persons');
    const select = $('#timelinePerson');
    if (!select) return;
    const previous = select.value;
    select.innerHTML = '<option value="">Todas as pessoas</option><option value="unknown">Não identificadas</option>' +
      state.persons.map(person => `<option value="${person.id}">${escapeHtml(person.name)} (${person.event_count || 0})</option>`).join('');
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
  } catch (_) {
    // Identity support is additive; timeline still works if this endpoint fails.
  }
}

function timelineTimestamp(dateValue, timeValue, endOfDay = false) {
  if (!dateValue) return null;
  const time = timeValue || (endOfDay ? '23:59:59' : '00:00:00');
  const local = new Date(`${dateValue}T${time}`);
  return Number.isNaN(local.getTime()) ? null : local.toISOString();
}

function timelineParams() {
  const params = new URLSearchParams();
  const cameraId = $('#timelineCamera')?.value || '';
  const person = $('#timelinePerson')?.value || '';
  const fromTs = timelineTimestamp($('#timelineDateFrom')?.value || '', $('#timelineTimeFrom')?.value || '', false);
  const toTs = timelineTimestamp($('#timelineDateTo')?.value || '', $('#timelineTimeTo')?.value || '', true);
  const face = $('#timelineFace')?.value ?? '';
  if (cameraId) params.set('camera_id', cameraId);
  if (person === 'unknown') params.set('unidentified', 'true');
  else if (person) params.set('person_id', person);
  if (fromTs) params.set('from_ts', fromTs);
  if (toTs) params.set('to_ts', toTs);
  if (face !== '') params.set('has_face', face === '1' ? 'true' : 'false');
  params.set('limit', '500');
  return params;
}

async function loadEvents() {
  try {
    const params = timelineParams();
    state.events = await api(`/api/events?${params.toString()}`);
    const visible = new Set(state.events.map(event => event.id));
    state.selectedEventIds = new Set([...state.selectedEventIds].filter(id => visible.has(id)));
    if ($('#eventCount')) $('#eventCount').textContent = state.events.length;
    renderTimeline();
  } catch (error) {
    if ($('#timelineGrid')) $('#timelineGrid').innerHTML = `<p class="muted">Falha ao carregar timeline: ${escapeHtml(error.message)}</p>`;
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

  if ($('#timelineCamera')) {
    const previous = $('#timelineCamera').value;
    $('#timelineCamera').innerHTML = '<option value="">Todas as câmeras</option>' + state.cameras.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    $('#timelineCamera').value = previous;
  }

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
  return `<article class="camera-card" data-id="${camera.id}"><div class="camera-preview">${preview}</div><div class="camera-meta"><div><h3>${escapeHtml(camera.name)}</h3><p>${escapeHtml(camera.location || 'Sem local definido')}</p></div><span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span></div></article>`;
}

function cameraRow(camera) {
  const [label, cls] = statusLabel(camera);
  return `<tr><td><strong>${escapeHtml(camera.name)}</strong></td><td>${escapeHtml(camera.location || '—')}</td><td><code>${escapeHtml(camera.rtsp_url_display)}</code></td><td><span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span></td><td><div class="table-actions"><button class="button ghost small" data-sync="${camera.id}">↻</button><button class="button ghost small" data-edit="${camera.id}">Editar</button><button class="button danger small" data-delete="${camera.id}">Excluir</button></div></td></tr>`;
}

function updateTimelineSelectionControls() {
  const count = state.selectedEventIds.size;
  const button = $('#timelineDeleteSelected');
  if (button) {
    button.disabled = count === 0;
    button.textContent = `Excluir selecionados (${count})`;
  }
  const selectAll = $('#timelineSelectAll');
  if (selectAll) {
    const allSelected = state.events.length > 0 && state.events.every(event => state.selectedEventIds.has(event.id));
    selectAll.textContent = allSelected ? 'Desmarcar todos' : 'Selecionar visíveis';
  }
}

function renderTimeline() {
  if (!$('#timelineGrid')) return;
  if (!state.events.length) {
    $('#timelineGrid').innerHTML = '<div class="empty-state compact"><div class="empty-icon">◷</div><h3>Nenhum evento encontrado</h3><p>Ajuste os filtros ou aguarde novas detecções.</p></div>';
    updateTimelineSelectionControls();
    return;
  }
  $('#timelineGrid').innerHTML = state.events.map(event => {
    const date = new Date(event.created_at);
    const when = Number.isNaN(date.getTime()) ? event.created_at : date.toLocaleString('pt-BR');
    const checked = state.selectedEventIds.has(event.id) ? 'checked' : '';
    const personLabel = event.person_name ? escapeHtml(event.person_name) : `Pessoa #${event.track_id ?? '—'}`;
    const identityClass = event.person_name ? 'identified' : '';
    return `<article class="event-card ${checked ? 'selected' : ''}" data-event-card="${event.id}">
      <div class="event-image">
        ${event.snapshot_url ? `<img src="${event.snapshot_url}" loading="lazy" alt="Evento da câmera ${escapeHtml(event.camera_name)}">` : '<div class="event-placeholder">Sem imagem</div>'}
        <label class="event-select" title="Selecionar evento"><input type="checkbox" data-select-event="${event.id}" ${checked} /><span>✓</span></label>
        <button class="event-delete" data-delete-event="${event.id}" title="Excluir este evento">×</button>
      </div>
      <div class="event-meta"><div><strong>${escapeHtml(event.camera_name)}</strong><span>${escapeHtml(event.camera_location || 'Sem local')}</span></div><span class="status-pill ${identityClass}">${personLabel}</span></div>
      <div class="event-foot"><span>${when}</span><span>${event.has_face ? `Face detectada${event.face_count > 1 ? ` (${event.face_count})` : ''}` : 'Sem face útil'}</span></div>
    </article>`;
  }).join('');
  $$('[data-delete-event]').forEach(el => el.addEventListener('click', (event) => { event.stopPropagation(); deleteTimelineEvent(Number(el.dataset.deleteEvent)); }));
  $$('[data-select-event]').forEach(el => el.addEventListener('change', () => {
    const id = Number(el.dataset.selectEvent);
    if (el.checked) state.selectedEventIds.add(id); else state.selectedEventIds.delete(id);
    renderTimeline();
  }));
  updateTimelineSelectionControls();
}

function toggleSelectAllTimelineEvents() {
  const allSelected = state.events.length > 0 && state.events.every(event => state.selectedEventIds.has(event.id));
  if (allSelected) state.events.forEach(event => state.selectedEventIds.delete(event.id));
  else state.events.forEach(event => state.selectedEventIds.add(event.id));
  renderTimeline();
}

async function deleteTimelineEvent(id) {
  if (!confirm('Excluir este evento e o snapshot salvo?')) return;
  try {
    await api(`/api/events/${id}`, { method: 'DELETE' });
    state.events = state.events.filter(event => event.id !== id);
    state.selectedEventIds.delete(id);
    if ($('#eventCount')) $('#eventCount').textContent = state.events.length;
    renderTimeline();
    toast('Evento excluído.');
  } catch (error) { toast(error.message, 'error'); }
}

async function deleteSelectedTimelineEvents() {
  const ids = [...state.selectedEventIds];
  if (!ids.length) return;
  if (!confirm(`Excluir ${ids.length} evento(s) selecionado(s) e seus snapshots?`)) return;
  try {
    const result = await api('/api/events/delete-bulk', { method: 'POST', body: JSON.stringify({ ids }) });
    state.selectedEventIds.clear();
    await loadEvents();
    toast(`${result.deleted || ids.length} evento(s) excluído(s).`);
  } catch (error) { toast(error.message, 'error'); }
}

async function deleteAllTimelineEvents() {
  const cameraId = $('#timelineCamera')?.value || '';
  const scope = cameraId ? 'todos os eventos desta câmera (independentemente dos demais filtros)' : 'TODOS os eventos da Timeline';
  if (!confirm(`Excluir ${scope} e seus snapshots? Esta ação não pode ser desfeita.`)) return;
  try {
    const suffix = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : '';
    await api(`/api/events${suffix}`, { method: 'DELETE' });
    state.selectedEventIds.clear();
    await loadEvents();
    await loadPersons();
    toast(cameraId ? 'Eventos desta câmera excluídos.' : 'Timeline limpa.');
  } catch (error) { toast(error.message, 'error'); }
}

function clearTimelineFilters() {
  ['timelineCamera', 'timelinePerson', 'timelineDateFrom', 'timelineDateTo', 'timelineTimeFrom', 'timelineTimeTo', 'timelineFace'].forEach(id => {
    const el = $(`#${id}`);
    if (el) el.value = '';
  });
  state.selectedEventIds.clear();
  loadEvents();
}

function setView(view) {
  state.view = view;
  const titles = { dashboard: 'Visão geral', cameras: 'Câmeras', timeline: 'Timeline', settings: 'Sistema' };
  $('#pageTitle').textContent = titles[view];
  $$('.view').forEach(el => el.classList.remove('active'));
  $(`#${view}View`).classList.add('active');
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  if (view === 'timeline') Promise.all([loadPersons(), loadEvents()]);
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
  $('#rtspHelp').textContent = camera ? `Atual: ${camera.rtsp_url_display}. Deixe vazio para manter a URL atual.` : 'A URL será armazenada apenas no SQLite local e enviada internamente ao go2rtc.';
  $('#cameraEnabled').checked = camera ? camera.enabled : true;
  $('#formError').classList.add('hidden');
  $('#cameraDialog').showModal();
}

async function saveCamera(event) {
  event.preventDefault();
  const id = Number($('#cameraId').value) || null;
  const payload = { name: $('#cameraName').value.trim(), location: $('#cameraLocation').value.trim(), enabled: $('#cameraEnabled').checked };
  const rtsp = $('#cameraRtsp').value.trim();
  if (rtsp) payload.rtsp_url = rtsp;
  const save = $('#saveCameraBtn');
  save.disabled = true;
  save.textContent = 'Salvando…';
  try {
    await api(id ? `/api/cameras/${id}` : '/api/cameras', { method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
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
  try { await api(`/api/cameras/${id}`, { method: 'DELETE' }); toast('Câmera excluída.'); await loadCameras(); }
  catch (error) { toast(error.message, 'error'); }
}

async function syncCamera(id) {
  try { toast('Sincronizando stream…'); await api(`/api/cameras/${id}/sync`, { method: 'POST' }); await Promise.all([loadCameras(), loadHealth()]); }
  catch (error) { toast(error.message, 'error'); }
}

async function syncAll() {
  try { toast('Sincronizando todas as câmeras…'); await api('/api/cameras/sync-all', { method: 'POST' }); await Promise.all([loadCameras(), loadHealth()]); toast('Sincronização concluída.'); }
  catch (error) { toast(error.message, 'error'); }
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
  list.innerHTML = devices.map(device => `<article class="discovery-device"><div class="discovery-device-main"><h3>${escapeHtml(device.ip)}</h3><p>Portas abertas: ${device.open_ports.join(', ')}</p><div class="discovery-badges">${device.rtsp ? '<span class="discovery-badge">RTSP :554</span>' : ''}${device.onvif ? '<span class="discovery-badge onvif">ONVIF :8899</span>' : ''}${device.already_added ? '<span class="discovery-badge added">Já cadastrada</span>' : ''}</div></div><button class="button ${device.already_added ? 'ghost' : 'primary'} small" data-configure-device="${escapeHtml(device.ip)}" ${device.already_added ? 'disabled' : ''}>${device.already_added ? 'Cadastrada' : 'Configurar'}</button></article>`).join('');
  $$('[data-configure-device]').forEach(el => el.addEventListener('click', () => configureDiscoveredDevice(el.dataset.configureDevice)));
}
