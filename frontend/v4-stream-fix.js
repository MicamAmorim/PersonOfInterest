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

  // Keep normal video on go2rtc's universal player. H.265 is not generally
  // negotiable through browser WebRTC, but the universal player can select MSE.
  // Audio/talkback uses a separate page whose WebRTC offer is audio-only.
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
        <div class="modal-actions">
          <button class="button ghost" type="button" data-review-close>Fechar</button>
          <button class="button danger" type="button" id="eventFalsePositiveBtn">Marcar como falso positivo</button>
        </div>
      </div>`;
    document.body.appendChild(dialog);
    dialog.querySelectorAll('[data-review-close]').forEach(el => el.addEventListener('click', () => dialog.close()));
    return dialog;
  }

  function reviewEvent(eventId) {
    const event = state.events.find(item => Number(item.id) === Number(eventId));
    if (!event) return;
    const dialog = ensureReviewDialog();
    const isFalse = event.identity_state === 'false_positive';
    dialog.dataset.eventId = String(event.id);
    document.getElementById('eventReviewTitle').textContent = event.camera_name || 'Detecção';
    document.getElementById('eventReviewSubtitle').textContent = `${formatReviewWhen(event.created_at)} · ${event.camera_location || 'Sem local'}`;
    document.getElementById('eventReviewImage').innerHTML = event.snapshot_url
      ? `<img src="${event.snapshot_url}" alt="Detecção para revisão">`
      : '<div class="event-placeholder">Sem imagem</div>';
    const identity = document.getElementById('eventReviewIdentity');
    identity.className = `status-pill ${isFalse ? 'false-positive' : (event.person_name ? 'identified' : '')}`;
    identity.textContent = isFalse ? 'Falso positivo' : (event.person_name || (event.unknown_cluster_id ? `Desconhecido #${event.unknown_cluster_id}` : `Pessoa #${event.track_id ?? '—'}`));
    document.getElementById('eventReviewHelp').textContent = isFalse
      ? 'Esta detecção está excluída de identidade, clustering, alertas e estatísticas. Você pode desfazer a classificação se ela estiver errada.'
      : 'Se isto não for uma pessoa real, marque como falso positivo. A amostra deixará de influenciar identidade, clusters, alertas e estatísticas.';
    const button = document.getElementById('eventFalsePositiveBtn');
    button.textContent = isFalse ? 'Desfazer falso positivo' : 'Marcar como falso positivo';
    button.classList.toggle('danger', !isFalse);
    button.classList.toggle('ghost', isFalse);
    button.onclick = () => setFalsePositive(event.id, !isFalse);
    if (!dialog.open) dialog.showModal();
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
        image.title = 'Clique para revisar esta detecção';
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

      if (isFalse) {
        card.querySelector('[data-identify-event]')?.remove();
        const pill = card.querySelector('.status-pill');
        if (pill) {
          pill.className = 'status-pill false-positive';
          pill.textContent = 'Falso positivo';
        }
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
