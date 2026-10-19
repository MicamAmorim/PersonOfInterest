(() => {
  const PROFILE_KEY = 'poi.doorbell.profile.v1';
  const DEFAULT_PROFILE = { name: '', dingdong: true, voice: false };
  let serverSettings = null;
  let spatialRules = [];

  const esc = value => {
    if (typeof escapeHtml === 'function') return escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>'"]/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);
  };

  const notify = (message, kind = 'info') => {
    if (typeof toast === 'function') toast(message, kind);
    else if (kind === 'error') alert(message);
    else console.log(message);
  };

  async function request(path, options = {}) {
    if (typeof api === 'function') return api(path, options);
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function loadProfile() {
    try {
      const raw = JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}');
      return {
        name: String(raw.name || '').trim().slice(0, 80),
        dingdong: raw.dingdong !== false,
        voice: Boolean(raw.voice),
      };
    } catch (_) {
      return { ...DEFAULT_PROFILE };
    }
  }

  function saveProfile(profile) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
    syncOverviewProfile();
  }

  function profileSummary(profile = loadProfile()) {
    const modes = [];
    if (profile.dingdong) modes.push('ding-dong');
    if (profile.voice) modes.push(profile.name ? `“${profile.name} chegou!”` : 'mensagem de voz');
    return modes.length ? modes.join(' + ') : 'sem saída configurada';
  }

  function installOverview() {
    const dashboard = document.getElementById('dashboardView');
    if (!dashboard || document.getElementById('doorbellOverviewCard')) return Boolean(dashboard);
    const stats = dashboard.querySelector('.stats-grid');
    if (!stats) return false;

    const card = document.createElement('div');
    card.id = 'doorbellOverviewCard';
    card.className = 'doorbell-overview-card';
    card.innerHTML = `
      <div class="doorbell-overview-copy">
        <p class="eyebrow">ATALHO DA CASA</p>
        <h3>Campainha</h3>
        <p class="muted" id="doorbellOverviewProfile"></p>
      </div>
      <div class="doorbell-actions">
        <button type="button" class="button ghost small" id="doorbellOpenSettings">Configurar em Alertas</button>
        <button type="button" class="button primary doorbell-ring-button" id="doorbellRingBtn"><span class="doorbell-icon">🔔</span> Campainha</button>
      </div>`;
    stats.insertAdjacentElement('afterend', card);
    document.getElementById('doorbellRingBtn')?.addEventListener('click', ringDoorbell);
    document.getElementById('doorbellOpenSettings')?.addEventListener('click', openAlerts);
    syncOverviewProfile();
    return true;
  }

  function syncOverviewProfile() {
    const label = document.getElementById('doorbellOverviewProfile');
    if (label) label.textContent = `Neste aparelho: ${profileSummary()}.`;
  }

  function openAlerts() {
    const nav = document.querySelector('[data-view="alerts"]');
    if (nav) nav.click();
    setTimeout(() => document.getElementById('doorbellPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120);
  }

  async function ringDoorbell() {
    const profile = loadProfile();
    if (!profile.dingdong && !profile.voice) {
      notify('Configure ding-dong, voz ou ambos em Alertas.', 'error');
      openAlerts();
      return;
    }
    if (profile.voice && !profile.name) {
      notify('Defina o nome deste aparelho antes de usar a mensagem de voz.', 'error');
      openAlerts();
      return;
    }
    const button = document.getElementById('doorbellRingBtn');
    if (button) button.disabled = true;
    try {
      const result = await request('/api/doorbell/ring', {
        method: 'POST',
        body: JSON.stringify({
          local_name: profile.name,
          dingdong: profile.dingdong,
          voice: profile.voice,
        }),
      });
      const count = result?.targets?.length || 0;
      notify(`Campainha enfileirada para ${count} ${count === 1 ? 'câmera' : 'câmeras'}.`, 'success');
    } catch (error) {
      notify(error?.message || 'Não foi possível tocar a campainha.', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function installAlertPanel() {
    const alerts = document.getElementById('alertsView');
    if (!alerts || document.getElementById('doorbellPanel')) return Boolean(alerts);
    const before = alerts.querySelector('.rules-panel');
    const panel = document.createElement('article');
    panel.id = 'doorbellPanel';
    panel.className = 'panel doorbell-settings-panel';
    panel.innerHTML = `
      <div class="panel-header">
        <div>
          <p class="eyebrow">CAMPAINHA · ALTO-FALANTES · PUSH</p>
          <h2>Campainha</h2>
          <p class="muted paragraph">O nome do botão manual fica somente neste navegador. As câmeras que devem tocar são uma configuração compartilhada da instalação.</p>
        </div>
        <button class="button ghost small" type="button" id="doorbellRefresh">↻ Atualizar</button>
      </div>

      <div class="doorbell-settings-grid">
        <section class="doorbell-card">
          <p class="eyebrow">ESTE APARELHO</p>
          <h3>Quem está tocando?</h3>
          <p class="muted">Salvo apenas no armazenamento local deste celular/computador.</p>
          <div class="doorbell-form">
            <label>Nome neste aparelho
              <input id="doorbellLocalName" type="text" maxlength="80" placeholder="Ex.: Miquéias" autocomplete="off" />
            </label>
            <div class="doorbell-check-row">
              <label class="doorbell-check"><input id="doorbellLocalDing" type="checkbox" /> Ding-dong</label>
              <label class="doorbell-check"><input id="doorbellLocalVoice" type="checkbox" /> Mensagem de voz</label>
            </div>
            <div class="doorbell-preview" id="doorbellLocalPreview"></div>
            <div class="doorbell-actions">
              <button class="button primary" type="button" id="doorbellSaveLocal">Salvar neste aparelho</button>
              <button class="button ghost" type="button" id="doorbellTestLocal">Tocar agora</button>
            </div>
          </div>
        </section>

        <section class="doorbell-card">
          <p class="eyebrow">INSTALAÇÃO</p>
          <h3>Onde a campainha toca?</h3>
          <p class="muted">Vale para todos os aparelhos que usam este PersonOfInterest.</p>
          <div class="doorbell-form">
            <div class="doorbell-radio-row">
              <label class="doorbell-radio"><input type="radio" name="doorbellTargets" id="doorbellTargetAll" value="all" /> Todos os alto-falantes</label>
              <label class="doorbell-radio"><input type="radio" name="doorbellTargets" id="doorbellTargetSelected" value="selected" /> Apenas selecionados</label>
            </div>
            <div id="doorbellCameraList" class="doorbell-camera-list"><p class="muted">Carregando câmeras…</p></div>
            <p class="eyebrow" style="margin:8px 0 0">QUANDO UMA REGRA ESPACIAL TOCAR A CAMPAINHA</p>
            <div class="doorbell-check-row">
              <label class="doorbell-check"><input id="doorbellSpatialDing" type="checkbox" /> Ding-dong</label>
              <label class="doorbell-check"><input id="doorbellSpatialVoice" type="checkbox" /> Voz: “Fulano chegou!” / “Alguém chegou!”</label>
            </div>
            <div class="doorbell-actions">
              <button class="button primary" type="button" id="doorbellSaveGlobal">Salvar alto-falantes</button>
            </div>
          </div>
        </section>
      </div>

      <div class="doorbell-section-title">
        <div>
          <p class="eyebrow">AUTOMAÇÃO</p>
          <h3>Alertas espaciais que tocam a campainha</h3>
          <p class="muted">A geometria, direção, permanência e cooldown continuam sendo controlados pela regra espacial original.</p>
        </div>
      </div>
      <div id="doorbellSpatialRules" class="doorbell-spatial-list"><p class="muted">Carregando regras…</p></div>`;
    alerts.insertBefore(panel, before || null);

    document.getElementById('doorbellRefresh')?.addEventListener('click', loadDoorbellSettings);
    document.getElementById('doorbellSaveLocal')?.addEventListener('click', saveLocalFromForm);
    document.getElementById('doorbellTestLocal')?.addEventListener('click', ringDoorbell);
    document.getElementById('doorbellSaveGlobal')?.addEventListener('click', saveGlobalFromForm);
    document.getElementById('doorbellTargetAll')?.addEventListener('change', syncCameraSelectionState);
    document.getElementById('doorbellTargetSelected')?.addEventListener('change', syncCameraSelectionState);
    ['doorbellLocalName', 'doorbellLocalDing', 'doorbellLocalVoice'].forEach(id => {
      document.getElementById(id)?.addEventListener('input', updateLocalPreview);
      document.getElementById(id)?.addEventListener('change', updateLocalPreview);
    });
    hydrateLocalForm();
    loadDoorbellSettings();
    return true;
  }

  function hydrateLocalForm() {
    const profile = loadProfile();
    const name = document.getElementById('doorbellLocalName');
    const ding = document.getElementById('doorbellLocalDing');
    const voice = document.getElementById('doorbellLocalVoice');
    if (name) name.value = profile.name;
    if (ding) ding.checked = profile.dingdong;
    if (voice) voice.checked = profile.voice;
    updateLocalPreview();
  }

  function profileFromForm() {
    return {
      name: String(document.getElementById('doorbellLocalName')?.value || '').trim().slice(0, 80),
      dingdong: Boolean(document.getElementById('doorbellLocalDing')?.checked),
      voice: Boolean(document.getElementById('doorbellLocalVoice')?.checked),
    };
  }

  function updateLocalPreview() {
    const preview = document.getElementById('doorbellLocalPreview');
    if (!preview) return;
    const profile = profileFromForm();
    if (!profile.dingdong && !profile.voice) {
      preview.textContent = 'Nenhuma saída selecionada.';
      return;
    }
    const parts = [];
    if (profile.dingdong) parts.push('🔔 ding-dong');
    if (profile.voice) parts.push(profile.name ? `🔊 “${profile.name} chegou!”` : '🔊 informe um nome para a voz');
    preview.textContent = parts.join('  +  ');
  }

  function saveLocalFromForm() {
    const profile = profileFromForm();
    if (!profile.dingdong && !profile.voice) {
      notify('Ative ding-dong, mensagem de voz ou ambos.', 'error');
      return;
    }
    if (profile.voice && !profile.name) {
      notify('Informe o nome deste aparelho para usar a mensagem de voz.', 'error');
      return;
    }
    saveProfile(profile);
    notify('Configuração deste aparelho salva localmente.', 'success');
  }

  async function loadDoorbellSettings() {
    const status = document.getElementById('doorbellCameraList');
    try {
      const [settings, rules] = await Promise.all([
        request('/api/doorbell/settings'),
        request('/api/doorbell/spatial-rules'),
      ]);
      serverSettings = settings;
      spatialRules = Array.isArray(rules) ? rules : [];
      renderGlobalSettings();
      renderSpatialRules();
    } catch (error) {
      if (status) status.innerHTML = `<p class="muted">${esc(error?.message || 'Falha ao carregar a campainha.')}</p>`;
    }
  }

  function renderGlobalSettings() {
    if (!serverSettings) return;
    const all = document.getElementById('doorbellTargetAll');
    const selected = document.getElementById('doorbellTargetSelected');
    if (all) all.checked = serverSettings.target_mode !== 'selected';
    if (selected) selected.checked = serverSettings.target_mode === 'selected';
    const ding = document.getElementById('doorbellSpatialDing');
    const voice = document.getElementById('doorbellSpatialVoice');
    if (ding) ding.checked = Boolean(serverSettings.spatial_dingdong);
    if (voice) voice.checked = Boolean(serverSettings.spatial_voice);

    const list = document.getElementById('doorbellCameraList');
    if (!list) return;
    const cameras = serverSettings.cameras || [];
    if (!cameras.length) {
      list.innerHTML = '<p class="muted">Nenhuma câmera cadastrada.</p>';
      return;
    }
    const selectedIds = new Set((serverSettings.camera_ids || []).map(Number));
    list.innerHTML = cameras.map(camera => {
      const online = camera.online && camera.enabled;
      const available = Boolean(camera.speaker_available);
      const meta = !available ? 'talkback não configurado' : (online ? 'alto-falante disponível' : 'offline agora');
      const dotClass = !available ? 'unavailable' : (online ? 'online' : '');
      return `<label class="doorbell-camera-item">
        <span class="doorbell-camera-main">
          <span class="doorbell-status-dot ${dotClass}"></span>
          <span><strong>${esc(camera.name)}</strong><div class="doorbell-camera-meta">${esc(meta)}</div></span>
        </span>
        <input class="doorbell-camera-choice" type="checkbox" value="${Number(camera.id)}" ${selectedIds.has(Number(camera.id)) ? 'checked' : ''} />
      </label>`;
    }).join('');
    syncCameraSelectionState();
  }

  function syncCameraSelectionState() {
    const selectedMode = Boolean(document.getElementById('doorbellTargetSelected')?.checked);
    document.querySelectorAll('.doorbell-camera-choice').forEach(input => {
      input.disabled = !selectedMode;
    });
  }

  async function saveGlobalFromForm() {
    const targetMode = document.getElementById('doorbellTargetSelected')?.checked ? 'selected' : 'all';
    const cameraIds = [...document.querySelectorAll('.doorbell-camera-choice:checked')].map(input => Number(input.value));
    if (targetMode === 'selected' && !cameraIds.length) {
      notify('Selecione ao menos uma câmera.', 'error');
      return;
    }
    const spatialDing = Boolean(document.getElementById('doorbellSpatialDing')?.checked);
    const spatialVoice = Boolean(document.getElementById('doorbellSpatialVoice')?.checked);
    if (!spatialDing && !spatialVoice && spatialRules.some(rule => rule.doorbell_enabled)) {
      notify('Há regras espaciais usando a campainha. Ative ding-dong, voz ou desative essas regras.', 'error');
      return;
    }
    const button = document.getElementById('doorbellSaveGlobal');
    if (button) button.disabled = true;
    try {
      serverSettings = await request('/api/doorbell/settings', {
        method: 'PUT',
        body: JSON.stringify({
          target_mode: targetMode,
          camera_ids: cameraIds,
          spatial_dingdong: spatialDing,
          spatial_voice: spatialVoice,
        }),
      });
      renderGlobalSettings();
      notify('Alto-falantes da campainha salvos.', 'success');
    } catch (error) {
      notify(error?.message || 'Não foi possível salvar a campainha.', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function renderSpatialRules() {
    const list = document.getElementById('doorbellSpatialRules');
    if (!list) return;
    if (!spatialRules.length) {
      list.innerHTML = '<p class="muted">Nenhuma regra espacial cadastrada.</p>';
      return;
    }
    list.innerHTML = spatialRules.map(rule => `<div class="doorbell-spatial-item">
      <div class="doorbell-spatial-main">
        <div><strong>${esc(rule.name)}</strong><div class="doorbell-spatial-meta">${esc(rule.camera_name)} · ${rule.kind === 'line_cross' ? 'linha direcional' : 'cerca'}${rule.rule_enabled ? '' : ' · regra desativada'}</div></div>
      </div>
      <label class="doorbell-switch" title="Tocar campainha quando esta regra disparar">
        <input type="checkbox" data-doorbell-rule="${Number(rule.rule_id)}" ${rule.doorbell_enabled ? 'checked' : ''} />
        <span></span>
      </label>
    </div>`).join('');
    list.querySelectorAll('[data-doorbell-rule]').forEach(input => {
      input.addEventListener('change', () => updateSpatialRule(input));
    });
  }

  async function updateSpatialRule(input) {
    const ruleId = Number(input.dataset.doorbellRule || 0);
    const enabled = Boolean(input.checked);
    input.disabled = true;
    try {
      await request(`/api/doorbell/spatial-rules/${ruleId}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled }),
      });
      const rule = spatialRules.find(item => Number(item.rule_id) === ruleId);
      if (rule) rule.doorbell_enabled = enabled;
      notify(enabled ? 'Campainha ativada nesta regra.' : 'Campainha desativada nesta regra.', 'success');
    } catch (error) {
      input.checked = !enabled;
      notify(error?.message || 'Não foi possível atualizar a regra.', 'error');
    } finally {
      input.disabled = false;
    }
  }

  function installAll() {
    const overview = installOverview();
    const alerts = installAlertPanel();
    return overview && alerts;
  }

  installAll();
  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    if (installAll() || attempts > 80) clearInterval(timer);
  }, 150);
})();
