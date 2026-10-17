(() => {
  function sameOriginStreamUrl(camera) {
    return `/go2rtc/stream.html?src=${encodeURIComponent(camera.stream_name)}`;
  }

  function audioViewerUrl(camera, speakerOn, micOn) {
    const params = new URLSearchParams({
      camera_id: String(camera.id),
      listen: speakerOn ? '1' : '0',
      microphone: micOn ? '1' : '0',
    });
    return `/camera-webrtc.html?${params.toString()}`;
  }

  viewerMediaUrl = function(camera, speakerOn, micOn) {
    if (!speakerOn && !micOn) return sameOriginStreamUrl(camera);
    return audioViewerUrl(camera, speakerOn, micOn);
  };

  cameraCard = function(camera) {
    const [label, cls] = statusLabel(camera);
    const preview = camera.enabled && camera.sync_status === 'ok'
      ? `<iframe src="${sameOriginStreamUrl(camera)}" title="${escapeHtml(camera.name)}" loading="lazy" allow="autoplay"></iframe><span class="live-badge">LIVE</span>`
      : `<div class="camera-preview disabled"><span>${camera.sync_status === 'error' ? 'Stream indisponível' : 'Câmera desativada'}</span></div>`;
    return `<article class="camera-card" data-id="${camera.id}"><div class="camera-preview">${preview}</div><div class="camera-meta"><div><h3>${escapeHtml(camera.name)}</h3><p>${escapeHtml(camera.location || 'Sem local definido')}</p></div><span class="status-pill ${cls}" title="${escapeHtml(camera.sync_error || '')}">${label}</span></div></article>`;
  };

  function formatReviewWhen(raw) {
    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? raw : date.toLocaleString('pt-BR');
  }

  function identityLabel(event) {
    if (event.identity_state === 'false_positive') return { text: 'Falso positivo', cls: 'false-positive' };
    if (event.person_name) {
      const confidence = event.identity_confidence != null ? ` · face ${Math.round(Number(event.identity_confidence) * 100)}%` : '';
      return { text: `${event.person_name}${confidence}`, cls: 'identified' };
    }
    if (event.probable_person_name) {
      const confidence = event.body_confidence != null ? ` · ${Math.round(Number(event.body_confidence) * 100)}%` : '';
      return { text: `Provável ${event.probable_person_name}${confidence}`, cls: 'probable' };
    }
    if (event.unknown_cluster_id) return { text: `Desconhecido #${event.unknown_cluster_id}`, cls: 'unknown' };
    if (event.identity_state === 'pending') return { text: 'Identificando…', cls: '' };
    return { text: `Pessoa #${event.track_id ?? '—'}`, cls: '' };
  }

  function ensureReviewDialog() {
    let dialog = document.getElementById('eventReviewDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'eventReviewDialog';
    dialog.className = 'modal event-review-modal';
    dialog.innerHTML = `
      <div class="event-review-shell">
        <div class="modal-header">
          <div><p class="eyebrow">REVISÃO MANUAL</p><h2 id="eventReviewTitle">Detecção</h2><span id="eventReviewSubtitle" class="muted"></span></div>
          <button class="icon-button" type="button" data-review-close>×</button>
        </div>
        <div id="eventReviewImage" class="event-review-image"></div>
        <div class="event-review-info">
          <span id="eventReviewIdentity" class="status-pill"></span>
          <p id="eventReviewHelp" class="muted paragraph"></p>
        </div>
        <div id="eventIdentityCorrection" class="event-identity-correction">
          <div class="identity-principle"><strong>Regra de identidade</strong><span>Face confirmada = identidade. Corpo = apenas provável. Uma correção manual sua também é tratada como confirmação.</span></div>
          <label>Pessoa existente
            <select id="eventReviewPersonSelect"><option value="">Escolha uma pessoa…</option></select>
          </label>
          <div class="event-or">ou</div>
          <label>Criar nova pessoa
            <input id="eventReviewNewName" maxlength="120" placeholder="Nome da pessoa" />
          </label>
          <button class="button primary" type="button" id="eventConfirmIdentityBtn">Confirmar / corrigir identidade</button>
        </div>
        <div class="modal-actions">
          <button class="button ghost" type="button" data-review-close>Fechar</button>
          <button class="button danger" type="button" id="eventFalsePositiveBtn">Marcar como falso positivo</button>
        </div>
      </div>`;
    document.body.appendChild(dialog);
    dialog.querySelectorAll('[data-review-close]').forEach(el => el.addEventListener('click', () => dialog.close()));
    return dialog;
  }

  function populateReviewPeople(event) {
    const select = document.getElementById('eventReviewPersonSelect');
    const input = document.getElementById('eventReviewNewName');
    if (!select || !input) return;
    select.innerHTML = '<option value="">Escolha uma pessoa…</option>' + (state.persons || []).map(person =>
      `<option value="${person.id}" ${Number(event.person_id) === Number(person.id) ? 'selected' : ''}>${escapeHtml(person.name)}</option>`
    ).join('');
    input.value = '';
    input.disabled = Boolean(select.value);
    select.onchange = () => {
      input.disabled = Boolean(select.value);
      if (select.value) input.value = '';
    };
    input.oninput = () => {
      if (input.value.trim()) select.value = '';
      input.disabled = false;
    };
  }

  function reviewEvent(eventId) {
    const event = state.events.find(item => Number(item.id) === Number(eventId));
    if (!event) return;
    const dialog = ensureReviewDialog();
    const isFalse = event.identity_state === 'false_positive';
    const label = identityLabel(event);
    dialog.dataset.eventId = String(event.id);
    document.getElementById('eventReviewTitle').textContent = event.camera_name || 'Detecção';
    document.getElementById('eventReviewSubtitle').textContent = `${formatReviewWhen(event.created_at)} · ${event.camera_location || 'Sem local'}`;
    document.getElementById('eventReviewImage').innerHTML = event.snapshot_url
      ? `<img src="${event.snapshot_url}" alt="Detecção para revisão">`
      : '<div class="event-placeholder">Sem imagem</div>';
    const identity = document.getElementById('eventReviewIdentity');
    identity.className = `status-pill ${label.cls}`;
    identity.textContent = label.text;

    let help = 'Você pode confirmar/corrigir a identidade ou marcar a detecção como falso positivo.';
    if (event.person_name) help = 'Identidade absoluta confirmada por face ou por revisão manual. Você pode corrigi-la abaixo se estiver errada.';
    else if (event.probable_person_name) {
      const reason = event.body_identity_source === 'face_linked_body'
        ? 'A aparência corporal combina com referências que já foram vistas junto de uma face confirmada.'
        : 'A aparência corporal combina com referências verificadas, mas corpo nunca vira identidade absoluta automaticamente.';
      help = `${reason} Confirme manualmente se desejar tornar esta detecção absoluta.`;
    } else if (isFalse) help = 'Esta detecção está excluída de identidade, clustering, alertas e estatísticas. Você pode desfazer a classificação.';
    document.getElementById('eventReviewHelp').textContent = help;

    const correction = document.getElementById('eventIdentityCorrection');
    correction.classList.toggle('hidden', isFalse);
    populateReviewPeople(event);
    document.getElementById('eventConfirmIdentityBtn').onclick = () => confirmEventIdentity(event.id);

    const button = document.getElementById('eventFalsePositiveBtn');
    button.textContent = isFalse ? 'Desfazer falso positivo' : 'Marcar como falso positivo';
    button.classList.toggle('danger', !isFalse);
    button.classList.toggle('ghost', isFalse);
    button.onclick = () => setFalsePositive(event.id, !isFalse);
    if (!dialog.open) dialog.showModal();
  }

  async function confirmEventIdentity(eventId) {
    const select = document.getElementById('eventReviewPersonSelect');
    const input = document.getElementById('eventReviewNewName');
    const personId = select?.value ? Number(select.value) : null;
    const name = input?.value.trim() || '';
    if (!personId && !name) {
      toast('Escolha uma pessoa existente ou informe um novo nome.', 'error');
      return;
    }
    const button = document.getElementById('eventConfirmIdentityBtn');
    if (button) button.disabled = true;
    try {
      const payload = personId ? { person_id: personId } : { name };
      const result = await api(`/api/identity/events/${eventId}/assign`, { method: 'POST', body: JSON.stringify(payload) });
      toast(`${result.person_name} confirmado(a) para esta identidade.`);
      const dialog = document.getElementById('eventReviewDialog');
      if (dialog?.open) dialog.close();
      await Promise.all([loadEvents(), loadPersons()]);
      if (state.view === 'identity') setView('identity');
      if (state.view === 'alerts') setView('alerts');
    } catch (error) {
      toast(`Identidade: ${error.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function setFalsePositive(eventId, value) {
    const button = document.getElementById('eventFalsePositiveBtn');
    if (button) button.disabled = true;
    try {
      await api(`/api/events/${eventId}/false-positive?value=${value ? 'true' : 'false'}`, { method: 'PATCH' });
      toast(value ? 'Detecção marcada como falso positivo.' : 'Falso positivo desfeito; o evento voltará para análise.');
      const dialog = document.getElementById('eventReviewDialog');
      if (dialog?.open) dialog.close();
      await loadEvents();
      if (state.view === 'identity') setView('identity');
      if (state.view === 'alerts') setView('alerts');
    } catch (error) {
      toast(`Revisão: ${error.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function enhanceTimelineFeedback() {
    for (const event of state.events || []) {
      const card = document.querySelector(`[data-event-card="${event.id}"]`);
      if (!card) continue;
      const isFalse = event.identity_state === 'false_positive';
      card.classList.toggle('false-positive', isFalse);

      const image = card.querySelector('.event-image img');
      if (image) {
        image.classList.add('reviewable-event-image');
        image.title = 'Clique para revisar ou corrigir esta detecção';
        image.onclick = (clickEvent) => {
          clickEvent.stopPropagation();
          reviewEvent(event.id);
        };
      }

      const actions = card.querySelector('.event-actions');
      if (actions && !actions.querySelector('[data-review-event]')) {
        const review = document.createElement('button');
        review.type = 'button';
        review.className = 'button ghost small';
        review.dataset.reviewEvent = String(event.id);
        review.textContent = 'Revisar';
        review.addEventListener('click', () => reviewEvent(event.id));
        actions.appendChild(review);
      }

      const pill = card.querySelector('.status-pill');
      const label = identityLabel(event);
      if (pill) {
        pill.className = `status-pill ${label.cls}`;
        pill.textContent = label.text;
      }

      if (event.probable_person_name && !event.person_name && !isFalse) {
        const faceText = card.querySelector('.event-foot span:last-child');
        if (faceText) faceText.textContent = event.body_identity_source === 'face_linked_body'
          ? 'Provável por corpo · referência ligada a face'
          : 'Provável por aparência corporal';
      }

      if (isFalse) {
        card.querySelector('[data-identify-event]')?.remove();
        const faceText = card.querySelector('.event-foot span:last-child');
        if (faceText) faceText.textContent = 'Ignorado pelo sistema';
      }
    }
  }

  const baseRenderTimeline = renderTimeline;
  renderTimeline = function() {
    baseRenderTimeline();
    enhanceTimelineFeedback();
  };

  try { render(); } catch (_) {}
  try { renderTimeline(); } catch (_) {}
})();
