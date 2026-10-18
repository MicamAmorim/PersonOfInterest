(() => {
  if (typeof state === 'undefined' || typeof api !== 'function') return;

  state.spatialRules = state.spatialRules || [];
  state.spatialEvents = state.spatialEvents || [];

  let editingId = null;
  let drawMode = 'points';
  let draft = { points: [], arrow_from: null, arrow_to: null };
  let arrowDragStart = null;
  let arrowPreview = null;
  let resizeObserver = null;

  function installSpatialPanel() {
    const alerts = document.getElementById('alertsView');
    if (!alerts || document.getElementById('spatialPanel')) return Boolean(alerts);
    const before = alerts.querySelector('.rules-panel');
    const panel = document.createElement('article');
    panel.id = 'spatialPanel';
    panel.className = 'panel spatial-panel';
    panel.innerHTML = `
      <div class="panel-header spatial-header">
        <div>
          <p class="eyebrow">CERCA VIRTUAL · DIREÇÃO</p>
          <h2>Alertas espaciais</h2>
          <p class="muted paragraph">Desenhe sobre a câmera. O ponto analisado é o <strong>pé da bounding box</strong> (centro da borda inferior), não o centro do corpo.</p>
          <p id="spatialStatus" class="spatial-status">Carregando regras espaciais…</p>
        </div>
        <button class="button ghost small" type="button" id="spatialRefresh">↻ Atualizar</button>
      </div>

      <div class="spatial-editor-grid">
        <div class="spatial-controls">
          <div class="spatial-form">
            <label>Câmera<select id="spatialCamera"></select></label>
            <label>Tipo<select id="spatialKind"><option value="line_cross">Linha direcional</option><option value="zone_dwell">Cerca / polígono</option></select></label>
            <label class="wide">Nome<input id="spatialName" maxlength="120" value="Entrada da garagem" /></label>
            <label class="spatial-zone-only hidden">Condição<select id="spatialZoneMode"><option value="inside">Permanecer dentro</option><option value="outside">Permanecer fora / sair</option></select></label>
            <label class="spatial-zone-only hidden">Tempo mínimo (s)<input id="spatialDwell" type="number" min="0" max="3600" step="1" value="5" /></label>
            <label>Cooldown (s)<input id="spatialCooldown" type="number" min="0" max="86400" step="1" value="30" /></label>
          </div>

          <div class="spatial-draw-actions">
            <button class="button ghost small active" type="button" id="spatialPointsMode">✎ Desenhar geometria</button>
            <button class="button ghost small spatial-line-only" type="button" id="spatialArrowMode">➜ Desenhar seta</button>
            <button class="button ghost small" type="button" id="spatialUndo">↶ Desfazer</button>
            <button class="button ghost small" type="button" id="spatialClear">Limpar</button>
          </div>

          <p id="spatialHelp" class="spatial-help"><strong>Linha:</strong> clique para criar os segmentos da polilinha. Depois escolha <strong>Desenhar seta</strong> e arraste no sentido que deve gerar o alerta.</p>
          <p class="spatial-help"><strong>Importante para PTZ:</strong> a geometria é relativa ao enquadramento. Se a câmera mover, a cerca também muda de referência física. O PersonOfInterest não desativa o auto-follow automaticamente.</p>

          <div class="spatial-save-row">
            <button class="button primary" type="button" id="spatialSave">Salvar regra</button>
            <button class="button ghost hidden" type="button" id="spatialCancelEdit">Cancelar edição</button>
            <span class="spacer"></span>
          </div>
        </div>

        <div class="spatial-stage-shell">
          <div class="spatial-stage" id="spatialStage">
            <iframe id="spatialFrame" title="Câmera para configuração da cerca" allow="autoplay" referrerpolicy="same-origin"></iframe>
            <canvas id="spatialCanvas"></canvas>
            <span class="spatial-stage-badge">pé da BB · coordenadas normalizadas</span>
          </div>
          <p class="spatial-stage-note">Linha: múltiplos cliques formam a polilinha; a seta é desenhada por arraste. Cerca: três ou mais pontos fecham automaticamente o polígono.</p>
        </div>
      </div>

      <div class="section-heading" style="margin-top:18px"><div><p class="eyebrow">SALVAS</p><h3>Regras espaciais</h3></div></div>
      <div id="spatialRuleList" class="spatial-rule-list"><p class="muted">Nenhuma regra carregada.</p></div>

      <div class="section-heading" style="margin-top:18px"><div><p class="eyebrow">HISTÓRICO</p><h3>Últimos disparos</h3></div></div>
      <div id="spatialEvents" class="spatial-events"><p class="muted">Nenhum disparo registrado.</p></div>`;
    alerts.insertBefore(panel, before || null);

    document.getElementById('spatialCamera')?.addEventListener('change', () => {
      if (!editingId) clearDraft(false);
      updateSpatialFrame();
    });
    document.getElementById('spatialKind')?.addEventListener('change', () => {
      clearDraft(false);
      syncSpatialKindUi();
    });
    document.getElementById('spatialPointsMode')?.addEventListener('click', () => setDrawMode('points'));
    document.getElementById('spatialArrowMode')?.addEventListener('click', () => setDrawMode('arrow'));
    document.getElementById('spatialUndo')?.addEventListener('click', undoDraft);
    document.getElementById('spatialClear')?.addEventListener('click', () => clearDraft(true));
    document.getElementById('spatialSave')?.addEventListener('click', saveSpatialRule);
    document.getElementById('spatialCancelEdit')?.addEventListener('click', cancelSpatialEdit);
    document.getElementById('spatialRefresh')?.addEventListener('click', loadSpatialAlerts);

    const canvas = document.getElementById('spatialCanvas');
    canvas?.addEventListener('pointerdown', onCanvasPointerDown);
    canvas?.addEventListener('pointermove', onCanvasPointerMove);
    canvas?.addEventListener('pointerup', onCanvasPointerUp);
    canvas?.addEventListener('pointercancel', onCanvasPointerCancel);
    canvas?.addEventListener('contextmenu', event => event.preventDefault());

    if (window.ResizeObserver && canvas) {
      resizeObserver = new ResizeObserver(() => resizeSpatialCanvas());
      resizeObserver.observe(document.getElementById('spatialStage'));
    } else {
      window.addEventListener('resize', resizeSpatialCanvas);
    }
    syncSpatialKindUi();
    setTimeout(resizeSpatialCanvas, 100);
    return true;
  }

  function currentKind() {
    return document.getElementById('spatialKind')?.value || 'line_cross';
  }

  function setDrawMode(mode) {
    if (mode === 'arrow' && currentKind() !== 'line_cross') mode = 'points';
    drawMode = mode;
    document.getElementById('spatialPointsMode')?.classList.toggle('active', mode === 'points');
    document.getElementById('spatialArrowMode')?.classList.toggle('active', mode === 'arrow');
    renderSpatialCanvas();
  }

  function syncSpatialKindUi() {
    const zone = currentKind() === 'zone_dwell';
    document.querySelectorAll('.spatial-zone-only').forEach(el => el.classList.toggle('hidden', !zone));
    document.querySelectorAll('.spatial-line-only').forEach(el => el.classList.toggle('hidden', zone));
    const help = document.getElementById('spatialHelp');
    if (help) help.innerHTML = zone
      ? '<strong>Cerca:</strong> clique em pelo menos três pontos. O polígono fecha automaticamente. Escolha se o alerta ocorre após permanecer dentro ou fora pelo tempo definido.'
      : '<strong>Linha:</strong> clique para criar os segmentos da polilinha. Depois escolha <strong>Desenhar seta</strong> e arraste no sentido que deve gerar o alerta.';
    if (zone && drawMode === 'arrow') setDrawMode('points');
    renderSpatialCanvas();
  }

  function populateSpatialCameras() {
    const select = document.getElementById('spatialCamera');
    if (!select) return;
    const previous = select.value;
    const cameras = state.cameras || [];
    select.innerHTML = cameras.length
      ? cameras.map(camera => `<option value="${camera.id}">${escapeHtml(camera.name)}</option>`).join('')
      : '<option value="">Nenhuma câmera</option>';
    if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
    updateSpatialFrame();
  }

  function selectedSpatialCamera() {
    const id = Number(document.getElementById('spatialCamera')?.value || 0);
    return (state.cameras || []).find(camera => Number(camera.id) === id) || null;
  }

  function updateSpatialFrame() {
    const frame = document.getElementById('spatialFrame');
    const camera = selectedSpatialCamera();
    if (!frame) return;
    if (!camera || !camera.enabled || camera.sync_status !== 'ok') {
      frame.removeAttribute('src');
      frame.srcdoc = '<body style="margin:0;background:#030507;color:#8d98a8;display:grid;place-items:center;height:100vh;font:14px sans-serif">Câmera indisponível</body>';
      return;
    }
    frame.removeAttribute('srcdoc');
    const url = `/camera-webrtc.html?camera_id=${encodeURIComponent(camera.id)}&listen=0&microphone=0`;
    if (!frame.src.endsWith(url)) frame.src = url;
  }

  function clearDraft(resetEdit) {
    draft = { points: [], arrow_from: null, arrow_to: null };
    arrowDragStart = null;
    arrowPreview = null;
    if (resetEdit) {
      editingId = null;
      document.getElementById('spatialSave').textContent = 'Salvar regra';
      document.getElementById('spatialCancelEdit')?.classList.add('hidden');
    }
    setDrawMode('points');
    renderSpatialCanvas();
  }

  function cancelSpatialEdit() {
    editingId = null;
    document.getElementById('spatialSave').textContent = 'Salvar regra';
    document.getElementById('spatialCancelEdit')?.classList.add('hidden');
    clearDraft(false);
  }

  function undoDraft() {
    if (drawMode === 'arrow' && (draft.arrow_from || draft.arrow_to)) {
      draft.arrow_from = null;
      draft.arrow_to = null;
    } else {
      draft.points.pop();
    }
    renderSpatialCanvas();
  }

  function normalizedPointer(event) {
    const canvas = document.getElementById('spatialCanvas');
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width))),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / Math.max(1, rect.height))),
    };
  }

  function onCanvasPointerDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    const canvas = event.currentTarget;
    const point = normalizedPointer(event);
    if (drawMode === 'arrow' && currentKind() === 'line_cross') {
      arrowDragStart = point;
      arrowPreview = point;
      canvas.setPointerCapture?.(event.pointerId);
    } else {
      draft.points.push(point);
      renderSpatialCanvas();
    }
  }

  function onCanvasPointerMove(event) {
    if (!arrowDragStart || drawMode !== 'arrow') return;
    arrowPreview = normalizedPointer(event);
    renderSpatialCanvas();
  }

  function onCanvasPointerUp(event) {
    if (!arrowDragStart || drawMode !== 'arrow') return;
    const end = normalizedPointer(event);
    const dx = end.x - arrowDragStart.x;
    const dy = end.y - arrowDragStart.y;
    if (dx * dx + dy * dy >= 0.0001) {
      draft.arrow_from = arrowDragStart;
      draft.arrow_to = end;
    }
    arrowDragStart = null;
    arrowPreview = null;
    renderSpatialCanvas();
  }

  function onCanvasPointerCancel() {
    arrowDragStart = null;
    arrowPreview = null;
    renderSpatialCanvas();
  }

  function resizeSpatialCanvas() {
    const canvas = document.getElementById('spatialCanvas');
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ratio = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    renderSpatialCanvas();
  }

  function canvasContext() {
    const canvas = document.getElementById('spatialCanvas');
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const ratio = canvas.width / Math.max(1, rect.width);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    return { canvas, ctx, width: rect.width, height: rect.height };
  }

  function drawArrow(ctx, from, to, width, height) {
    if (!from || !to) return;
    const x1 = from.x * width, y1 = from.y * height;
    const x2 = to.x * width, y2 = to.y * height;
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const head = 13;
    ctx.save();
    ctx.strokeStyle = '#ffcd63';
    ctx.fillStyle = '#ffcd63';
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6));
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  function renderSpatialCanvas() {
    const info = canvasContext();
    if (!info) return;
    const { ctx, width, height } = info;
    const points = draft.points || [];
    const zone = currentKind() === 'zone_dwell';
    if (points.length) {
      ctx.save();
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#5fd4ff';
      ctx.fillStyle = 'rgba(95,212,255,.13)';
      ctx.beginPath();
      points.forEach((point, index) => {
        const x = point.x * width, y = point.y * height;
        if (!index) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      if (zone && points.length >= 3) {
        ctx.closePath();
        ctx.fill();
      }
      ctx.stroke();
      for (const point of points) {
        ctx.beginPath();
        ctx.fillStyle = '#dff6ff';
        ctx.arc(point.x * width, point.y * height, 4.5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
    if (!zone) {
      drawArrow(ctx, draft.arrow_from, draft.arrow_to, width, height);
      if (arrowDragStart && arrowPreview) drawArrow(ctx, arrowDragStart, arrowPreview, width, height);
    }
  }

  function spatialPayload() {
    const cameraId = Number(document.getElementById('spatialCamera')?.value || 0);
    if (!cameraId) throw new Error('Escolha uma câmera.');
    const kind = currentKind();
    if (kind === 'line_cross' && draft.points.length < 2) throw new Error('Desenhe pelo menos dois pontos para a linha.');
    if (kind === 'line_cross' && (!draft.arrow_from || !draft.arrow_to)) throw new Error('Desenhe a seta de direção.');
    if (kind === 'zone_dwell' && draft.points.length < 3) throw new Error('Desenhe pelo menos três pontos para a cerca.');
    return {
      name: document.getElementById('spatialName')?.value.trim() || 'Cerca virtual',
      camera_id: cameraId,
      kind,
      points: draft.points,
      arrow_from: kind === 'line_cross' ? draft.arrow_from : null,
      arrow_to: kind === 'line_cross' ? draft.arrow_to : null,
      zone_mode: kind === 'zone_dwell' ? document.getElementById('spatialZoneMode')?.value || 'inside' : null,
      dwell_seconds: kind === 'zone_dwell' ? Math.max(0, Number(document.getElementById('spatialDwell')?.value || 0)) : 0,
      cooldown_seconds: Math.max(0, Number(document.getElementById('spatialCooldown')?.value || 30)),
      enabled: true,
    };
  }

  async function saveSpatialRule() {
    const button = document.getElementById('spatialSave');
    try {
      const payload = spatialPayload();
      if (button) button.disabled = true;
      if (editingId) {
        await api(`/api/spatial-alerts/rules/${editingId}`, { method: 'PATCH', body: JSON.stringify(payload) });
        toast('Regra espacial atualizada.');
      } else {
        await api('/api/spatial-alerts/rules', { method: 'POST', body: JSON.stringify(payload) });
        toast('Regra espacial criada.');
      }
      editingId = null;
      clearDraft(true);
      await loadSpatialAlerts();
    } catch (error) {
      toast(`Cerca virtual: ${error.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function editSpatialRule(id) {
    const rule = state.spatialRules.find(item => Number(item.id) === Number(id));
    if (!rule) return;
    editingId = Number(rule.id);
    document.getElementById('spatialCamera').value = String(rule.camera_id);
    document.getElementById('spatialKind').value = rule.kind;
    document.getElementById('spatialName').value = rule.name || '';
    document.getElementById('spatialZoneMode').value = rule.zone_mode || 'inside';
    document.getElementById('spatialDwell').value = String(rule.dwell_seconds ?? 5);
    document.getElementById('spatialCooldown').value = String(rule.cooldown_seconds ?? 30);
    draft = {
      points: (rule.points || []).map(point => ({ x: Number(point.x), y: Number(point.y) })),
      arrow_from: rule.arrow_from ? { x: Number(rule.arrow_from.x), y: Number(rule.arrow_from.y) } : null,
      arrow_to: rule.arrow_to ? { x: Number(rule.arrow_to.x), y: Number(rule.arrow_to.y) } : null,
    };
    document.getElementById('spatialSave').textContent = 'Salvar alterações';
    document.getElementById('spatialCancelEdit')?.classList.remove('hidden');
    syncSpatialKindUi();
    setDrawMode('points');
    updateSpatialFrame();
    renderSpatialCanvas();
    document.getElementById('spatialPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function toggleSpatialRule(id, enabled) {
    try {
      await api(`/api/spatial-alerts/rules/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) });
      await loadSpatialAlerts();
    } catch (error) { toast(error.message, 'error'); }
  }

  async function deleteSpatialRule(id) {
    if (!confirm('Excluir esta cerca virtual?')) return;
    try {
      await api(`/api/spatial-alerts/rules/${id}`, { method: 'DELETE' });
      if (editingId === id) cancelSpatialEdit();
      await loadSpatialAlerts();
    } catch (error) { toast(error.message, 'error'); }
  }

  function renderSpatialRules() {
    const list = document.getElementById('spatialRuleList');
    if (!list) return;
    if (!state.spatialRules.length) {
      list.innerHTML = '<p class="muted">Nenhuma linha ou cerca virtual criada.</p>';
      return;
    }
    list.innerHTML = state.spatialRules.map(rule => {
      const kind = rule.kind === 'line_cross' ? 'Linha direcional' : 'Cerca';
      const detail = rule.kind === 'line_cross'
        ? `${rule.points?.length || 0} ponto(s) · direção obrigatória · cooldown ${Math.round(Number(rule.cooldown_seconds || 0))}s`
        : `${rule.zone_mode === 'outside' ? 'fora / saída' : 'dentro'} por ${Number(rule.dwell_seconds || 0)}s · cooldown ${Math.round(Number(rule.cooldown_seconds || 0))}s`;
      return `<article class="spatial-rule-row">
        <div class="spatial-rule-meta"><strong>${escapeHtml(rule.name)}</strong><span>${escapeHtml(kind)} · ${escapeHtml(rule.camera_name || 'Câmera')} · ${escapeHtml(detail)}</span></div>
        <div class="spatial-rule-actions">
          <label class="mini-switch"><input type="checkbox" data-spatial-toggle="${rule.id}" ${rule.enabled ? 'checked' : ''}><span>${rule.enabled ? 'Ativa' : 'Pausada'}</span></label>
          <button class="button ghost small" type="button" data-spatial-edit="${rule.id}">Editar</button>
          <button class="button danger small" type="button" data-spatial-delete="${rule.id}">Excluir</button>
        </div>
      </article>`;
    }).join('');
    document.querySelectorAll('[data-spatial-toggle]').forEach(el => el.addEventListener('change', () => toggleSpatialRule(Number(el.dataset.spatialToggle), el.checked)));
    document.querySelectorAll('[data-spatial-edit]').forEach(el => el.addEventListener('click', () => editSpatialRule(Number(el.dataset.spatialEdit))));
    document.querySelectorAll('[data-spatial-delete]').forEach(el => el.addEventListener('click', () => deleteSpatialRule(Number(el.dataset.spatialDelete))));
  }

  function renderSpatialEvents() {
    const list = document.getElementById('spatialEvents');
    if (!list) return;
    if (!state.spatialEvents.length) {
      list.innerHTML = '<p class="muted">Nenhum disparo espacial registrado.</p>';
      return;
    }
    list.innerHTML = state.spatialEvents.slice(0, 12).map(event => {
      const label = event.trigger_kind === 'line_cross' ? 'cruzou na direção configurada' : event.trigger_kind === 'zone_inside' ? 'permanência dentro' : 'permanência fora';
      const date = new Date(event.created_at);
      const when = Number.isNaN(date.getTime()) ? event.created_at : date.toLocaleString('pt-BR');
      return `<div class="spatial-event"><strong>${escapeHtml(event.rule_name)} · ${escapeHtml(label)}</strong><span>${escapeHtml(event.camera_name)} · track ${event.track_id ?? '—'} · ${escapeHtml(when)}</span></div>`;
    }).join('');
  }

  async function loadSpatialAlerts() {
    if (!installSpatialPanel()) return;
    try {
      if (!state.cameras?.length) state.cameras = await api('/api/cameras');
      const [rules, status, events] = await Promise.all([
        api('/api/spatial-alerts/rules'),
        api('/api/spatial-alerts/status'),
        api('/api/spatial-alerts/events?limit=30'),
      ]);
      state.spatialRules = rules || [];
      state.spatialEvents = events || [];
      populateSpatialCameras();
      renderSpatialRules();
      renderSpatialEvents();
      const statusEl = document.getElementById('spatialStatus');
      if (statusEl) {
        const last = status.last_trigger?.rule_name ? ` · último: ${status.last_trigger.rule_name}` : '';
        statusEl.textContent = `${status.enabled_rules || 0} regra(s) ativa(s) · ponto de análise: centro inferior da BB${last}${status.error ? ` · erro: ${status.error}` : ''}`;
      }
      setTimeout(resizeSpatialCanvas, 50);
    } catch (error) {
      const statusEl = document.getElementById('spatialStatus');
      if (statusEl) statusEl.textContent = `Cerca virtual: ${error.message}`;
    }
  }

  document.querySelector('[data-view="alerts"]')?.addEventListener('click', () => setTimeout(loadSpatialAlerts, 60));
  if (!installSpatialPanel()) setTimeout(installSpatialPanel, 80);
  setTimeout(() => {
    if (state.view === 'alerts' || new URLSearchParams(location.search).get('view') === 'alerts') loadSpatialAlerts();
  }, 350);
})();
