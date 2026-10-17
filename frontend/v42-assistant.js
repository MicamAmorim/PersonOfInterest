(() => {
  if (typeof state === 'undefined' || typeof api !== 'function') return;

  state.assistantSettings = [];
  state.assistantStatus = null;

  function browserTimezone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
    catch (_) { return 'UTC'; }
  }

  function installAssistantPanel() {
    const grid = document.querySelector('#alertsView .settings-grid.v4-grid');
    if (!grid || document.getElementById('assistantPanel')) return false;

    const panel = document.createElement('article');
    panel.id = 'assistantPanel';
    panel.className = 'panel info-panel';
    panel.innerHTML = `
      <p class="eyebrow">V4.2 · VOZ NA CÂMERA</p>
      <h2>Assistente</h2>
      <p class="muted paragraph">Cumprimenta pessoas usando a identidade local. Face/manual é confirmação; corpo continua sempre <strong>provável</strong> e o nome é falado como pergunta.</p>
      <div class="alert-form assistant-form">
        <label>Câmera
          <select id="assistantCamera"></select>
        </label>
        <label>Intervalo depois da saudação (min)
          <input id="assistantInterval" type="number" min="1" max="1440" step="1" value="30" />
        </label>
        <label>Voz
          <select id="assistantVoice">
            <option value="female">Feminina · Francisca</option>
            <option value="male">Masculina · Antonio</option>
          </select>
        </label>
        <label>Fuso horário
          <input id="assistantTimezone" value="${escapeHtml(browserTimezone())}" maxlength="80" />
        </label>
      </div>
      <label class="switch-row assistant-switch">
        <span><strong>Assistente ligado</strong><small>Fala somente para novos eventos depois de ser ativado.</small></span>
        <input id="assistantEnabled" type="checkbox" />
      </label>
      <p id="assistantStatusText" class="field-help">Carregando assistente…</p>
      <div class="push-actions">
        <button class="button primary" type="button" id="assistantSaveBtn">Salvar assistente</button>
        <button class="button ghost" type="button" id="assistantTestBtn">▶ Testar voz</button>
        <button class="button ghost" type="button" id="assistantRefreshBtn">↻ Atualizar</button>
      </div>
      <p class="field-help">Primeira aparição da pessoa em cada turno: Bom dia / Boa tarde / Boa noite. Depois, o assistente respeita o intervalo configurado. Uma face desconhecida de boa qualidade recebe “Oi, quem é?”.</p>`;
    grid.appendChild(panel);

    document.getElementById('assistantCamera')?.addEventListener('change', renderSelectedAssistant);
    document.getElementById('assistantSaveBtn')?.addEventListener('click', saveAssistantSettings);
    document.getElementById('assistantTestBtn')?.addEventListener('click', testAssistantVoice);
    document.getElementById('assistantRefreshBtn')?.addEventListener('click', loadAssistantSettings);
    return true;
  }

  function selectedSetting() {
    const id = Number(document.getElementById('assistantCamera')?.value || 0);
    return state.assistantSettings.find(item => Number(item.camera_id) === id) || null;
  }

  function populateCameras() {
    const select = document.getElementById('assistantCamera');
    if (!select) return;
    const previous = select.value;
    select.innerHTML = state.assistantSettings.length
      ? state.assistantSettings.map(item => `<option value="${item.camera_id}">${escapeHtml(item.camera_name || `Câmera ${item.camera_id}`)}</option>`).join('')
      : '<option value="">Nenhuma câmera</option>';
    if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
  }

  function renderSelectedAssistant() {
    const setting = selectedSetting();
    const enabled = document.getElementById('assistantEnabled');
    const interval = document.getElementById('assistantInterval');
    const voice = document.getElementById('assistantVoice');
    const timezone = document.getElementById('assistantTimezone');
    if (!enabled || !interval || !voice || !timezone) return;

    enabled.checked = Boolean(setting?.enabled);
    interval.value = String(setting?.interval_minutes || 30);
    voice.value = setting?.voice_gender || 'female';
    timezone.value = setting?.updated_at
      ? (setting.timezone || browserTimezone())
      : browserTimezone();

    const status = document.getElementById('assistantStatusText');
    if (!status) return;
    if (!state.assistantStatus) {
      status.textContent = 'Assistente: status indisponível.';
      return;
    }
    const body = Number(state.assistantStatus.body_probable_threshold || 0).toFixed(2);
    const unknown = Number(state.assistantStatus.unknown_face_quality_threshold || 0).toFixed(2);
    const last = state.assistantStatus.last_speech;
    const lastText = last?.text ? ` · última fala: “${last.text}”` : '';
    const error = state.assistantStatus.error ? ` · ${state.assistantStatus.error}` : '';
    status.textContent = `Motor: ${state.assistantStatus.status} · limiar corporal ≥ ${body} · qualidade de face desconhecida ≥ ${unknown}${lastText}${error}`;
  }

  async function loadAssistantSettings() {
    installAssistantPanel();
    const statusEl = document.getElementById('assistantStatusText');
    try {
      const [settings, status] = await Promise.all([
        api('/api/assistant/settings'),
        api('/api/assistant/status'),
      ]);
      state.assistantSettings = settings || [];
      state.assistantStatus = status || null;
      populateCameras();
      renderSelectedAssistant();
    } catch (error) {
      if (statusEl) statusEl.textContent = `Assistente indisponível: ${error.message}`;
    }
  }

  async function saveAssistantSettings({ quiet = false } = {}) {
    const cameraId = Number(document.getElementById('assistantCamera')?.value || 0);
    if (!cameraId) {
      if (!quiet) toast('Escolha uma câmera para o assistente.', 'error');
      return false;
    }
    const button = document.getElementById('assistantSaveBtn');
    if (button) button.disabled = true;
    const payload = {
      enabled: Boolean(document.getElementById('assistantEnabled')?.checked),
      interval_minutes: Number(document.getElementById('assistantInterval')?.value || 30),
      voice_gender: document.getElementById('assistantVoice')?.value || 'female',
      timezone: document.getElementById('assistantTimezone')?.value.trim() || browserTimezone(),
    };
    try {
      const saved = await api(`/api/assistant/cameras/${cameraId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      const index = state.assistantSettings.findIndex(item => Number(item.camera_id) === cameraId);
      if (index >= 0) state.assistantSettings[index] = saved;
      else state.assistantSettings.push(saved);
      renderSelectedAssistant();
      if (!quiet) toast(saved.enabled ? 'Assistente ligado e configurações salvas.' : 'Assistente desligado e configurações salvas.');
      return true;
    } catch (error) {
      toast(`Assistente: ${error.message}`, 'error');
      return false;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function testAssistantVoice() {
    const cameraId = Number(document.getElementById('assistantCamera')?.value || 0);
    if (!cameraId) { toast('Escolha uma câmera.', 'error'); return; }
    const button = document.getElementById('assistantTestBtn');
    if (button) {
      button.disabled = true;
      button.textContent = 'Gerando voz…';
    }
    try {
      if (!(await saveAssistantSettings({ quiet: true }))) return;
      const result = await api(`/api/assistant/cameras/${cameraId}/test`, { method: 'POST', body: '{}' });
      toast(`Teste enviado: ${result.text}`);
      setTimeout(loadAssistantSettings, 700);
    } catch (error) {
      toast(`Teste do assistente: ${error.message}`, 'error');
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = '▶ Testar voz';
      }
    }
  }

  function hookAlertsNavigation() {
    document.querySelector('[data-view="alerts"]')?.addEventListener('click', () => {
      setTimeout(loadAssistantSettings, 30);
    });
  }

  if (!installAssistantPanel()) setTimeout(installAssistantPanel, 0);
  hookAlertsNavigation();
  setTimeout(loadAssistantSettings, 450);
})();
