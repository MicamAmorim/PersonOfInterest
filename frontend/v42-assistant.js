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
      <p class="eyebrow">V4.5 · TONHO CONVERSA</p>
      <h2>Assistente</h2>
      <p class="muted paragraph">Cumprimenta pessoas usando a identidade local. Face/manual é confirmação; corpo continua sempre <strong>provável</strong>. Com <strong>“Oi, Tonho!”</strong>, abre uma pequena janela de conversa para perguntas simples sobre esta câmera.</p>

      <div class="assistant-active-block">
        <div class="assistant-active-heading"><strong>Assistentes ativos</strong><span id="assistantActiveCount" class="muted">0</span></div>
        <div id="assistantActiveList" class="assistant-active-list"><p class="muted">Carregando…</p></div>
      </div>

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
      <label class="switch-row assistant-switch tonho-switch">
        <span><strong>Escutar “Oi, Tonho!”</strong><small>Transcrição local pelo Whisper. Pode responder na mesma frase ou aguardar uma pergunta curta depois de “Pode falar”.</small></span>
        <input id="assistantWakeEnabled" type="checkbox" />
      </label>
      <p id="assistantWakeStatusText" class="field-help">Tonho: aguardando configuração…</p>
      <p id="assistantStatusText" class="field-help">Carregando assistente…</p>
      <div class="push-actions">
        <button class="button primary" type="button" id="assistantSaveBtn">Salvar assistente</button>
        <button class="button ghost" type="button" id="assistantTestBtn">▶ Testar voz</button>
        <button class="button ghost" type="button" id="assistantRefreshBtn">↻ Atualizar</button>
      </div>
      <p class="field-help"><strong>Exemplos do Tonho:</strong> “Quem sou eu?”, “Quem está aqui?”, “Quem passou aqui hoje?”, “Quando Andressa passou por aqui?”, “Quantas pessoas passaram hoje?”, “Tem alguém desconhecido?” e “Que horas são?”. Você também pode falar tudo de uma vez: “Oi, Tonho, quem passou aqui hoje?”.</p>
      <p class="field-help">Primeira aparição da pessoa em cada turno: Bom dia / Boa tarde / Boa noite. Depois, o assistente respeita o intervalo configurado. Uma face desconhecida de boa qualidade recebe “Oi, quem é?”.</p>`;
    grid.appendChild(panel);

    document.getElementById('assistantCamera')?.addEventListener('change', renderSelectedAssistant);
    document.getElementById('assistantEnabled')?.addEventListener('change', syncWakeAvailability);
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

  function renderActiveAssistants() {
    const list = document.getElementById('assistantActiveList');
    const count = document.getElementById('assistantActiveCount');
    if (!list || !count) return;
    const active = (state.assistantSettings || []).filter(item => Boolean(item.enabled));
    count.textContent = active.length === 1 ? '1 ativo' : `${active.length} ativos`;
    if (!active.length) {
      list.innerHTML = '<p class="muted">Nenhum assistente está ligado.</p>';
      return;
    }
    list.innerHTML = active.map(item => {
      const voice = item.voice_gender === 'male' ? 'Antonio · masculina' : 'Francisca · feminina';
      const interval = Number(item.interval_minutes || 30);
      const wake = item.wake_enabled ? ' · 🎙 Oi, Tonho ativo' : '';
      return `<div class="assistant-active-row" data-assistant-active-camera="${item.camera_id}">
        <div><strong>${escapeHtml(item.camera_name || `Câmera ${item.camera_id}`)}</strong><span>${escapeHtml(voice)} · ${interval} min · ${escapeHtml(item.timezone || 'UTC')}${wake}</span></div>
        <button class="button ghost small" type="button">Configurar</button>
      </div>`;
    }).join('');
    list.querySelectorAll('[data-assistant-active-camera]').forEach(row => {
      row.addEventListener('click', () => {
        const select = document.getElementById('assistantCamera');
        if (!select) return;
        select.value = String(row.dataset.assistantActiveCamera || '');
        renderSelectedAssistant();
        document.getElementById('assistantEnabled')?.focus();
      });
    });
  }

  function syncWakeAvailability() {
    const enabled = document.getElementById('assistantEnabled');
    const wake = document.getElementById('assistantWakeEnabled');
    if (!enabled || !wake) return;
    wake.disabled = !enabled.checked;
    if (!enabled.checked) wake.checked = false;
  }

  function renderWakeStatus(setting) {
    const el = document.getElementById('assistantWakeStatusText');
    if (!el) return;
    const wake = state.assistantStatus?.wake_word;
    if (!setting?.wake_enabled) {
      el.textContent = 'Tonho: escuta desligada nesta câmera.';
      return;
    }
    if (!wake) {
      el.textContent = 'Tonho: status indisponível.';
      return;
    }
    if (!wake.available) {
      el.textContent = `Tonho indisponível: ${wake.runtime_error || 'runtime de voz não carregado'}`;
      return;
    }
    const cameraState = wake.cameras?.[String(setting.camera_id)] || wake.cameras?.[setting.camera_id];
    const status = cameraState?.status || wake.status || 'iniciando';
    const conversation = Number(wake.conversation_seconds || 8);
    const waiting = cameraState?.conversation_open ? ` · aguardando pergunta por ${conversation}s` : '';
    const intent = cameraState?.last_intent ? ` · comando: ${cameraState.last_intent}` : '';
    const heard = cameraState?.last_transcript ? ` · ouvi: “${cameraState.last_transcript}”` : '';
    const answer = cameraState?.last_response ? ` · respondi: “${cameraState.last_response}”` : '';
    const error = cameraState?.error ? ` · ${cameraState.error}` : '';
    el.textContent = `Tonho: ${status} · frase “${wake.phrase || 'Oi, Tonho!'}” · Whisper ${wake.model || 'tiny'} · janela ${conversation}s${waiting}${intent}${heard}${answer}${error}`;
  }

  function renderSelectedAssistant() {
    const setting = selectedSetting();
    const enabled = document.getElementById('assistantEnabled');
    const wake = document.getElementById('assistantWakeEnabled');
    const interval = document.getElementById('assistantInterval');
    const voice = document.getElementById('assistantVoice');
    const timezone = document.getElementById('assistantTimezone');
    if (!enabled || !wake || !interval || !voice || !timezone) return;

    enabled.checked = Boolean(setting?.enabled);
    wake.checked = Boolean(setting?.wake_enabled && setting?.enabled);
    interval.value = String(setting?.interval_minutes || 30);
    voice.value = setting?.voice_gender || 'female';
    timezone.value = setting?.updated_at
      ? (setting.timezone || browserTimezone())
      : browserTimezone();
    syncWakeAvailability();
    renderWakeStatus(setting);

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
      renderActiveAssistants();
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
    const enabled = Boolean(document.getElementById('assistantEnabled')?.checked);
    const payload = {
      enabled,
      interval_minutes: Number(document.getElementById('assistantInterval')?.value || 30),
      voice_gender: document.getElementById('assistantVoice')?.value || 'female',
      timezone: document.getElementById('assistantTimezone')?.value.trim() || browserTimezone(),
      wake_enabled: enabled && Boolean(document.getElementById('assistantWakeEnabled')?.checked),
    };
    try {
      const saved = await api(`/api/assistant/cameras/${cameraId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      const index = state.assistantSettings.findIndex(item => Number(item.camera_id) === cameraId);
      if (index >= 0) state.assistantSettings[index] = saved;
      else state.assistantSettings.push(saved);
      renderActiveAssistants();
      renderSelectedAssistant();
      if (!quiet) {
        const wakeText = saved.wake_enabled ? ' Escuta “Oi, Tonho!” e conversa curta ativas.' : '';
        toast(saved.enabled ? `Assistente ligado e configurações salvas.${wakeText}` : 'Assistente desligado e configurações salvas.');
      }
      setTimeout(loadAssistantSettings, 900);
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
