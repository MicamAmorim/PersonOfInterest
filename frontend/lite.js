const byId = (id) => document.getElementById(id);
const cameraPicker = byId('live-camera');
const recordingPicker = byId('recording-camera');
const form = byId('camera-form');
const dialog = byId('camera-dialog');
let cameras = [];
let activeView = '';
let editingId = null;
let recordingsRequest = 0;

function element(tag, className, label) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (label !== undefined) node.textContent = label;
  return node;
}

function setMessage(id, message = '') {
  const node = byId(id);
  node.textContent = message;
  node.hidden = !message;
}

async function api(path, method = 'GET', data) {
  const options = { method, cache: 'no-store' };
  if (data) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `Erro ${response.status}`);
  }
  return response.json();
}

function applySelection(select, items, placeholder) {
  const previous = select.value;
  select.replaceChildren(new Option(placeholder, ''), ...items.map((camera) => new Option(camera.name, camera.id)));
  select.value = items.some((camera) => String(camera.id) === previous) ? previous : '';
}

function renderLive() {
  const live = byId('live-player');
  const camera = cameras.find((item) => item.id === Number(cameraPicker.value));
  if (!camera) {
    live.replaceChildren(element('p', 'muted', 'Selecione uma câmera ativa.'));
    return;
  }
  if (camera.sync_status !== 'ok') {
    live.replaceChildren(element('p', 'muted', 'Fluxo indisponível. Sincronize a câmera na aba Câmeras.'));
    return;
  }
  const frame = element('iframe');
  frame.title = `Vídeo ao vivo de ${camera.name}`;
  frame.allow = 'autoplay; fullscreen';
  frame.src = `${camera.viewer_url}&background=false`;
  live.replaceChildren(frame);
}

function actionButton(label, action, className = 'button ghost small') {
  const button = element('button', className, label);
  button.type = 'button';
  button.addEventListener('click', action);
  return button;
}

async function renderCameras() {
  const [settings, status] = await Promise.all([api('/api/recording/settings'), api('/api/recording/status')]);
  setMessage('recording-warning', status.paused_for_space
    ? 'Gravação pausada. Libere espaço no aparelho para retomar.'
    : status.ffmpeg_available ? '' : 'FFmpeg indisponível para gravação.');
  const rows = cameras.map((camera) => {
    const row = element('article', 'panel lite-row');
    const description = element('div');
    const states = { ok: 'Fluxo configurado', error: 'Erro no fluxo', pending: 'Pendente', disabled: 'Desativada' };
    const recording = status.sessions.some((item) => item.camera_id === camera.id && item.running);
    description.append(element('h2', '', camera.name), element('p', 'muted', [camera.location, states[camera.sync_status], recording ? 'Gravando' : ''].filter(Boolean).join(' · ')));

    const controls = element('div', 'lite-controls');
    const label = element('label', '', 'Gravação');
    const select = element('select');
    const setting = settings.find((item) => item.camera_id === camera.id);
    select.append(new Option('Desativada', 'off'), new Option('Contínua', 'continuous'));
    if (setting?.mode === 'event') {
      const unsupported = new Option('Por evento (versão completa)', 'event');
      unsupported.disabled = true;
      select.add(unsupported);
    }
    let savedMode = setting?.mode ?? 'off';
    select.value = savedMode;
    select.addEventListener('change', async () => {
      select.disabled = true;
      try {
        await api(`/api/recording/settings/${camera.id}`, 'PATCH', { mode: select.value });
        savedMode = select.value;
        setMessage('page-error');
      } catch (error) {
        select.value = savedMode;
        setMessage('page-error', error.message);
      } finally {
        select.disabled = false;
      }
    });
    label.append(select);
    const sync = actionButton('Sincronizar', async () => {
      sync.disabled = true;
      try {
        await api(`/api/cameras/${camera.id}/sync`, 'POST');
        await refresh();
      } catch (error) {
        setMessage('page-error', error.message);
      } finally {
        sync.disabled = false;
      }
    });
    controls.append(label, sync, actionButton('Editar', () => editCamera(camera)));
    row.append(description, controls);
    return row;
  });
  byId('camera-list').replaceChildren(...(rows.length ? rows : [element('p', 'muted', 'Nenhuma câmera cadastrada.')]));
}

async function renderRecordings() {
  const version = ++recordingsRequest;
  const filter = recordingPicker.value ? `?camera_id=${encodeURIComponent(recordingPicker.value)}` : '';
  const recordings = await api(`/api/recordings${filter}`);
  if (version !== recordingsRequest || activeView !== 'recordings') return;
  const rows = recordings.map((recording) => {
    const row = element('div', 'lite-row');
    const time = new Date(recording.started_at || recording.created_at).toLocaleString('pt-BR');
    row.append(element('span', '', `${recording.camera_name} · ${time}`));
    row.append(actionButton('Reproduzir', async () => {
      const player = byId('recording-player');
      player.src = recording.file_url;
      player.hidden = false;
      try { await player.play(); }
      catch { setMessage('page-error', 'O navegador não conseguiu reproduzir esta gravação.'); }
    }));
    return row;
  });
  byId('recording-list').replaceChildren(...(rows.length ? rows : [element('p', 'muted', 'Nenhuma gravação encontrada.')]));
}

function editCamera(camera) {
  form.reset();
  editingId = camera?.id ?? null;
  form.elements.name.value = camera?.name ?? '';
  form.elements.location.value = camera?.location ?? '';
  form.elements.enabled.checked = camera?.enabled ?? true;
  form.elements.rtsp_url.required = !editingId;
  byId('rtsp-help').hidden = !editingId;
  byId('camera-dialog-title').textContent = editingId ? 'Editar câmera' : 'Adicionar câmera';
  setMessage('camera-form-error');
  dialog.showModal();
}

async function refresh() {
  setMessage('page-error');
  try {
    const [health, catalog] = await Promise.all([api('/api/health'), api('/api/cameras')]);
    cameras = catalog;
    byId('health-dot').classList.toggle('ok', health.go2rtc === 'ok');
    byId('health-label').textContent = health.go2rtc === 'ok' ? 'Servidor online' : 'Servidor online · vídeo indisponível';
    const enabled = cameras.filter((camera) => camera.enabled);
    applySelection(cameraPicker, enabled, 'Selecione');
    if (!cameraPicker.value && enabled.length === 1) cameraPicker.value = enabled[0].id;
    applySelection(recordingPicker, cameras, 'Todas');
    if (activeView === 'live') renderLive();
    if (activeView === 'cameras') await renderCameras();
    if (activeView === 'recordings') await renderRecordings();
  } catch (error) {
    byId('health-dot').classList.remove('ok');
    byId('health-label').textContent = 'Conexão indisponível';
    setMessage('page-error', error.message);
  }
}

function openView() {
  const requested = new URL(location.href).searchParams.get('view');
  const page = requested === 'timeline' ? 'recordings' : requested;
  activeView = ['live', 'cameras', 'recordings'].includes(page) ? page : 'live';
  for (const link of document.querySelectorAll('[data-view]')) {
    const selected = link.dataset.view === activeView;
    link.classList.toggle('active', selected);
    if (selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
    byId(link.dataset.view).hidden = !selected;
  }
  if (activeView !== 'live') byId('live-player').replaceChildren();
  if (activeView !== 'recordings') {
    const player = byId('recording-player');
    if (player.hasAttribute('src')) {
      player.pause();
      player.removeAttribute('src');
      player.load();
      player.hidden = true;
    }
  }
  void refresh();
}

document.querySelector('nav').addEventListener('click', (event) => {
  const link = event.target.closest('[data-view]');
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  history.pushState({}, '', link.href);
  openView();
});
window.addEventListener('popstate', openView);
cameraPicker.addEventListener('change', renderLive);
recordingPicker.addEventListener('change', () => renderRecordings().catch((error) => setMessage('page-error', error.message)));
byId('refresh-recordings').addEventListener('click', refresh);
byId('new-camera').addEventListener('click', () => editCamera(null));
byId('cancel-camera').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => form.reset());

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage('camera-form-error');
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  const data = { name: form.elements.name.value.trim(), location: form.elements.location.value, enabled: form.elements.enabled.checked };
  const address = form.elements.rtsp_url.value.trim();
  if (address) data.rtsp_url = address;
  try {
    await api(editingId ? `/api/cameras/${editingId}` : '/api/cameras', editingId ? 'PATCH' : 'POST', data);
    dialog.close();
    await refresh();
  } catch (error) {
    setMessage('camera-form-error', error.message);
  } finally {
    submit.disabled = false;
  }
});

openView();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
