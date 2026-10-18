(() => {
  if (typeof state === 'undefined' || typeof api !== 'function') return;

  state.assistantSettings = [];
  state.assistantStatus = null;
  state.assistantLogs = null;

  const FALLBACK_WAKE_MODELS = ['tiny', 'base', 'small'];
  const FALLBACK_COMMAND_MODELS = ['base', 'small', 'medium'];

  function browserTimezone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
    catch (_) { return 'UTC'; }
  }

  function installAssistantPanel() {
    const grid = document.querySelector('#alertsView .settings-grid.v4-grid');
    if (!grid || document.getElementById('assistantPanel')) return false;

    const panel = document.createElement('article');
    panel.id = 'assistantPanel';
    panel.className = 'panel info-panel tonho-panel';
    panel.innerHTML = `
      <div class="tonho-panel-head">
        <div>
          <p class="eyebrow">V4.7 · TONHO</p>
          <h2>Assistente</h2>
          <p class="muted paragraph">Identidade e histórico continuam locais. Face/manual é confirmação; corpo é sempre <strong>provável</strong>. O Whisper selecionado abaixo faz a escuta e os comandos.</p>
        </div>
        <a class="button ghost small tonho-lab-link" href="/tonho-lab.html">🎙 Tonho Lab</a>
      </div>

      <div class="assistant-active-block">
        <div class="assistant-active-heading"><strong>Assistentes ativos</strong><span id="assistantActiveCount" class="muted">0</span></div>
        <div id="assistantActiveList" class="assistant-active-list"><p class="muted">Carregando…</p></div>
      </div>

      <section class="tonho-section">
        <div class="tonho-section-title"><strong>Configuração da câmera</strong><span>Saudação, voz e contexto</span></div>
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
      </section>

      <section class="tonho-section tonho-model-section">
        <div class="tonho-section-title"><strong>Modelos Whisper</strong><span>Se não estiver no cache, será baixado ao ativar/salvar.</span></div>
        <div class="alert-form assistant-form tonho-model-grid">
          <label>Modelo de ativação / escuta
            <select id="assistantWakeModel"></select>
            <small>Roda continuamente. <strong>base</strong> é o equilíbrio recomendado.</small>
          </label>
          <label>Modelo de comandos
            <select id="assistantCommandModel"></select>
            <small><strong>small</strong> é o padrão. <strong>medium</strong> prioriza precisão, com mais latência/CPU.</small>
          </label>
        </div>
        <div id="assistantModelStatus" class="tonho-model-status"></div>
      </section>

      <div class="tonho-switches">
        <label class="switch-row assistant-switch">
          <span><strong>Assistente ligado</strong><small>Saudações automáticas por identidade e eventos novos.</small></span>
          <input id="assistantEnabled" type="checkbox" />
        </label>
        <label class="switch-row assistant-switch tonho-switch">
          <span><strong>Escutar “Oi, Tonho!”</strong><small>Ativa a escuta contínua e a janela de conversa curta.</small></span>
          <input id="assistantWakeEnabled" type="checkbox" />
        </label>
      </div>

      <div class="push-actions tonho-actions">
        <button class="button primary" type="button" id="assistantSaveBtn">Salvar assistente</button>
        <button class="button ghost" type="button" id="assistantTestBtn">▶ Testar voz</button>
        <button class="button ghost" type="button" id="assistantRefreshBtn">↻ Atualizar</button>
      </div>
      <div id="assistantStatusText" class="tonho-engine-line">Carregando assistente…</div>

      <section class="tonho-console">
        <div class="tonho-console-head">
          <div>
            <strong>Diagnóstico do Tonho</strong>
            <span>Última passagem pelo pipeline desta câmera</span>
          </div>
          <span id="assistantWakeStatusBadge" class="tonho-status-badge">aguardando</span>
        </div>

        <div class="tonho-console-grid">
          <div class="tonho-console-cell"><span>Escuta ouviu</span><strong id="tonhoFastTranscript">—</strong></div>
          <div class="tonho-console-cell"><span>Comando ouviu</span><strong id="tonhoCommandTranscript">—</strong></div>
          <div class="tonho-console-cell"><span>Prompt / comando</span><strong id="tonhoCommand">—</strong></div>
          <div class="tonho-console-cell"><span>Intent · rota</span><strong id="tonhoIntentRoute">—</strong></div>
          <div class="tonho-console-cell tonho-console-wide"><span>Resposta</span><strong id="tonhoResponse">—</strong></div>
          <div class="tonho-console-cell tonho-console-wide"><span>Estado / erro</span><strong id="tonhoError">—</strong></div>
        </div>

        <div class="tonho-prompt-box">
          <div class="tonho-prompt-head">
            <strong>Prompt de teste</strong>
            <span>Testa parser + ferramentas sem depender do microfone.</span>
          </div>
          <div class="tonho-prompt-row">
            <input id="assistantPromptInput" type="text" value="Quem passou por aqui?" placeholder="Digite uma pergunta para o Tonho…" />
            <button class="button ghost" id="assistantPromptBtn" type="button">Executar</button>
          </div>
          <label class="tonho-inline-check"><input id="assistantPromptSpeak" type="checkbox" /> também falar a resposta na câmera</label>
          <div id="assistantPromptResult" class="tonho-prompt-result">Nenhum prompt executado nesta sessão.</div>
        </div>

        <div class="tonho-log-block">
          <div class="tonho-log-head">
            <div><strong>Log recente</strong><span>Wake, transcrições e falas do assistente</span></div>
            <button class="button ghost small" id="assistantLogRefreshBtn" type="button">↻</button>
          </div>
          <div id="assistantLogList" class="tonho-log-list"><p class="muted">Carregando…</p></div>
        </div>
      </section>

      <details class="tonho-help">
        <summary>O que o Tonho entende hoje?</summary>
        <p>Exemplos: “Quem sou eu?”, “Quem está aqui?”, “Quem passou por aqui?”, “Quando Andressa passou por aqui?”, “Quantas pessoas passaram hoje?”, “Tem alguém desconhecido?” e “Que horas são?”. Você pode falar tudo de uma vez depois de “Oi, Tonho”.</p>
        <p>Primeira aparição em cada turno recebe Bom dia / Boa tarde / Boa noite. Depois, vale o intervalo configurado. Uma face desconhecida de boa qualidade recebe “Oi, quem é?”.</p>
      </details>`;
    grid.appendChild(panel);

    document.getElementById('assistantCamera')?.addEventListener('change', () => {
      renderSelectedAssistant();
      loadAssistantLogs();
    });
    document.getElementById('assistantEnabled')?.addEventListener('change', syncWakeAvailability);
    document.getElementById('assistantWakeModel')?.addEventListener('change', renderModelStatus);
    document.getElementById('assistantCommandModel')?.addEventListener('change', renderModelStatus);
    document.getElementById('assistantSaveBtn')?.addEventListener('click', saveAssistantSettings);
    document.getElementById('assistantTestBtn')?.addEventListener('click', testAssistantVoice);
    document.getElementById('assistantRefreshBtn')?.addEventListener('click', loadAssistantSettings);
    document.getElementById('assistantLogRefreshBtn')?.addEventListener('click', loadAssistantLogs);
    document.getElementById('assistantPromptBtn')?.addEventListener('click', testAssistantPrompt);
    document.getElementById('assistantPromptInput')?.addEventListener('keydown', event => {
      if (event.key === 'Enter') testAssistantPrompt();
    });
    return true;
  }

  function selectedSetting() {
    const id = Number(document.getElementById('assistantCamera')?.value || 0);
    return state.assistantSettings.find(item => Number(item.camera_id) === id) || null;
  }

  function modelOptions(kind) {
    const wake = state.assistantStatus?.wake_word;
    const options = wake?.model_options?.[kind];
    if (Array.isArray(options) && options.length) return options;
    return kind === 'wake' ? FALLBACK_WAKE_MODELS : FALLBACK_COMMAND_MODELS;
  }

  function fillModelSelect(id, kind, selected) {
    const select = document.getElementById(id);
    if (!select) return;
    const options = modelOptions(kind);
    select.innerHTML = options.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    const fallback = kind === 'wake' ? 'base' : 'small';
    select.value = options.includes(selected) ? selected : (options.includes(fallback) ? fallback : options[0]);
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
      const models = item.wake_enabled ? ` · 🎙 ${item.wake_model || 'base'} → ${item.command_model || 'small'}` : '';
      return `<div class="assistant-active-row" data-assistant-active-camera="${item.camera_id}">
        <div><strong>${escapeHtml(item.camera_name || `Câmera ${item.camera_id}`)}</strong><span>${escapeHtml(voice)} · ${interval} min · ${escapeHtml(item.timezone || 'UTC')}${escapeHtml(models)}</span></div>
        <button class="button ghost small" type="button">Configurar</button>
      </div>`;
    }).join('');
    list.querySelectorAll('[data-assistant-active-camera]').forEach(row => {
      row.addEventListener('click', () => {
        const select = document.getElementById('assistantCamera');
        if (!select) return;
        select.value = String(row.dataset.assistantActiveCamera || '');
        renderSelectedAssistant();
        loadAssistantLogs();
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

  function cameraWakeState(setting) {
    const wake = state.assistantStatus?.wake_word;
    return wake?.cameras?.[String(setting?.camera_id)] || wake?.cameras?.[setting?.camera_id] || null;
  }

  function renderModelStatus() {
    const el = document.getElementById('assistantModelStatus');
    if (!el) return;
    const wake = state.assistantStatus?.wake_word;
    const selectedWake = document.getElementById('assistantWakeModel')?.value || 'base';
    const selectedCommand = document.getElementById('assistantCommandModel')?.value || 'small';
    const loaded = new Set(wake?.loaded_models || []);
    const states = wake?.model_states || {};

    function modelChip(name, label) {
      const info = states?.[name];
      let status = loaded.has(name) ? 'carregado' : 'não carregado';
      let cls = loaded.has(name) ? 'loaded' : 'idle';
      if (info?.status === 'loading') { status = 'baixando / carregando'; cls = 'loading'; }
      if (info?.status === 'error') { status = 'erro'; cls = 'error'; }
      const title = info?.error ? ` title="${escapeHtml(info.error)}"` : '';
      return `<span class="tonho-model-chip ${cls}"${title}><b>${escapeHtml(label)}</b> ${escapeHtml(name)} · ${escapeHtml(status)}</span>`;
    }

    el.innerHTML = modelChip(selectedWake, 'escuta') + modelChip(selectedCommand, 'comando');
  }

  function renderWakeConsole(setting) {
    const wake = state.assistantStatus?.wake_word;
    const cameraState = cameraWakeState(setting) || {};
    const status = cameraState.status || (setting?.wake_enabled ? wake?.status : 'desligado') || 'iniciando';
    const badge = document.getElementById('assistantWakeStatusBadge');
    if (badge) {
      badge.textContent = String(status).replaceAll('_', ' ');
      badge.dataset.status = status;
    }
    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value || '—';
    };
    setText('tonhoFastTranscript', cameraState.last_fast_transcript || cameraState.last_transcript);
    setText('tonhoCommandTranscript', cameraState.last_command_transcript);
    setText('tonhoCommand', cameraState.last_command);
    const intentRoute = [cameraState.last_intent, cameraState.last_route || cameraState.last_stt_route].filter(Boolean).join(' · ');
    setText('tonhoIntentRoute', intentRoute);
    setText('tonhoResponse', cameraState.last_response);
    const error = cameraState.error || cameraState.command_model_error || cameraState.model_preload_error;
    const waiting = cameraState.conversation_open ? `aguardando pergunta · ${Number(wake?.conversation_seconds || 10)}s` : '';
    setText('tonhoError', error || waiting || 'sem erro');
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
    timezone.value = setting?.updated_at ? (setting.timezone || browserTimezone()) : browserTimezone();
    fillModelSelect('assistantWakeModel', 'wake', setting?.wake_model || 'base');
    fillModelSelect('assistantCommandModel', 'command', setting?.command_model || 'small');
    syncWakeAvailability();
    renderModelStatus();
    renderWakeConsole(setting);

    const status = document.getElementById('assistantStatusText');
    if (!status) return;
    if (!state.assistantStatus) {
      status.textContent = 'Motor indisponível.';
      return;
    }
    const body = Number(state.assistantStatus.body_probable_threshold || 0).toFixed(2);
    const unknown = Number(state.assistantStatus.unknown_face_quality_threshold || 0).toFixed(2);
    const error = state.assistantStatus.error ? ` · erro: ${state.assistantStatus.error}` : '';
    status.innerHTML = `<span>Motor <strong>${escapeHtml(state.assistantStatus.status || '—')}</strong></span><span>corpo provável ≥ <strong>${body}</strong></span><span>face desconhecida ≥ <strong>${unknown}</strong></span>${error ? `<span>${escapeHtml(error)}</span>` : ''}`;
  }

  function formatLogTime(raw) {
    if (!raw) return '';
    try { return new Date(raw).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
    catch (_) { return raw; }
  }

  function renderLogs(data) {
    const list = document.getElementById('assistantLogList');
    if (!list) return;
    const entries = [];
    (data?.wake || []).forEach(item => entries.push({
      time: item.created_at,
      type: item.matched ? 'wake' : 'heard',
      label: item.matched ? 'WAKE' : 'STT',
      input: item.transcript,
      output: item.response_text,
      error: null,
    }));
    (data?.speech || []).forEach(item => entries.push({
      time: item.spoken_at,
      type: item.status === 'error' ? 'error' : 'speech',
      label: item.kind || 'FALA',
      input: null,
      output: item.text,
      error: item.error,
    }));
    entries.sort((a, b) => String(b.time || '').localeCompare(String(a.time || '')));
    const recent = entries.slice(0, 16);
    if (!recent.length) {
      list.innerHTML = '<p class="muted">Ainda não há registros para esta câmera.</p>';
      return;
    }
    list.innerHTML = recent.map(item => `
      <div class="tonho-log-row ${escapeHtml(item.type)}">
        <div class="tonho-log-meta"><span class="tonho-log-badge">${escapeHtml(item.label)}</span><time>${escapeHtml(formatLogTime(item.time))}</time></div>
        <div class="tonho-log-copy">
          ${item.input ? `<div><span>entrada</span><strong>${escapeHtml(item.input)}</strong></div>` : ''}
          ${item.output ? `<div><span>saída</span><strong>${escapeHtml(item.output)}</strong></div>` : ''}
          ${item.error ? `<div class="error"><span>erro</span><strong>${escapeHtml(item.error)}</strong></div>` : ''}
        </div>
      </div>`).join('');
  }

  async function loadAssistantLogs() {
    const cameraId = Number(document.getElementById('assistantCamera')?.value || 0);
    if (!cameraId) return;
    const list = document.getElementById('assistantLogList');
    if (list) list.innerHTML = '<p class="muted">Carregando log…</p>';
    try {
      state.assistantLogs = await api(`/api/assistant/cameras/${cameraId}/logs?limit=20`);
      renderLogs(state.assistantLogs);
    } catch (error) {
      if (list) list.innerHTML = `<p class="muted">Log indisponível: ${escapeHtml(error.message)}</p>`;
    }
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
      await loadAssistantLogs();
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
      wake_model: document.getElementById('assistantWakeModel')?.value || 'base',
      command_model: document.getElementById('assistantCommandModel')?.value || 'small',
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
        const models = saved.wake_enabled ? ` Modelos ${saved.wake_model} → ${saved.command_model} sendo preparados.` : '';
        toast(saved.enabled ? `Assistente salvo.${models}` : 'Assistente desligado e configurações salvas.');
      }
      setTimeout(loadAssistantSettings, 1100);
      return true;
    } catch (error) {
      toast(`Assistente: ${error.message}`, 'error');
      return false;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function testAssistantPrompt() {
    const cameraId = Number(document.getElementById('assistantCamera')?.value || 0);
    const input = document.getElementById('assistantPromptInput');
    const resultEl = document.getElementById('assistantPromptResult');
    const button = document.getElementById('assistantPromptBtn');
    const text = input?.value.trim() || '';
    if (!cameraId || !text) return;
    if (button) button.disabled = true;
    if (resultEl) resultEl.textContent = 'Processando…';
    try {
      const result = await api('/api/assistant/lab/text', {
        method: 'POST',
        body: JSON.stringify({
          camera_id: cameraId,
          text,
          require_wake: false,
          speak: Boolean(document.getElementById('assistantPromptSpeak')?.checked),
        }),
      });
      if (resultEl) {
        resultEl.innerHTML = `<span>${escapeHtml(result.intent || '—')}</span><strong>${escapeHtml(result.answer || '—')}</strong>`;
      }
      const command = document.getElementById('tonhoCommand');
      const intent = document.getElementById('tonhoIntentRoute');
      const answer = document.getElementById('tonhoResponse');
      if (command) command.textContent = result.command || text;
      if (intent) intent.textContent = `${result.intent || '—'} · prompt_manual`;
      if (answer) answer.textContent = result.answer || '—';
      setTimeout(loadAssistantLogs, 500);
    } catch (error) {
      if (resultEl) resultEl.textContent = `Erro: ${error.message}`;
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
