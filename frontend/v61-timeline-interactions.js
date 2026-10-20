(() => {
  const V61 = {
    selectedEventId: null,
    observer: null,
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function eventCard(id) {
    return document.querySelector(`#poiEventStrip [data-event-card="${Number(id)}"]`);
  }

  function eventMarker(id) {
    return document.querySelector(`#poiEventMarkers [data-event-id="${Number(id)}"]`);
  }

  function selectedFromDom() {
    const card = document.querySelector('#poiEventStrip .poi-event-card.selected');
    if (card?.dataset.eventCard) return Number(card.dataset.eventCard);
    const marker = document.querySelector('#poiEventMarkers .poi-event-marker.selected');
    if (marker?.dataset.eventId) return Number(marker.dataset.eventId);
    return null;
  }

  function scrollCardToCenter(card) {
    const strip = document.getElementById('poiEventStrip');
    if (!strip || !card) return;
    const target = card.offsetLeft - (strip.clientWidth / 2) + (card.offsetWidth / 2);
    strip.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
  }

  function updateClassifyButton() {
    const button = document.getElementById('poiTimelineClassify');
    if (!button) return;
    const id = V61.selectedEventId || selectedFromDom();
    button.hidden = !id;
    if (id) button.dataset.eventId = String(id);
    else delete button.dataset.eventId;
  }

  function syncSelection(eventId, { scrollCard = false } = {}) {
    const id = Number(eventId || 0) || null;
    if (id) V61.selectedEventId = id;

    document.querySelectorAll('#poiEventStrip [data-event-card]').forEach(card => {
      card.classList.toggle('selected', id != null && Number(card.dataset.eventCard) === id);
    });
    document.querySelectorAll('#poiEventMarkers [data-event-id]').forEach(marker => {
      marker.classList.toggle('selected', id != null && Number(marker.dataset.eventId) === id);
    });

    const card = id ? eventCard(id) : null;
    if (scrollCard && card) scrollCardToCenter(card);
    updateClassifyButton();
  }

  function cardInfo(eventId) {
    const card = eventCard(eventId);
    const marker = eventMarker(eventId);
    const time = card?.querySelector('.poi-event-card-meta b')?.textContent?.trim() || '';
    const label = card?.querySelector('.poi-event-card-meta strong')?.textContent?.trim() || `Evento #${eventId}`;
    const isFalsePositive = Boolean(marker?.classList.contains('fp')) || label.toLowerCase().includes('falso positivo');
    return { card, marker, time, label, isFalsePositive };
  }

  function closeClassifyDialog() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    if (!dialog) return;
    try { dialog.close(); }
    catch (_) { dialog.removeAttribute('open'); }
  }

  function installClassifyDialog() {
    if (document.getElementById('poiTimelineClassifyDialog')) return;
    const dialog = document.createElement('dialog');
    dialog.id = 'poiTimelineClassifyDialog';
    dialog.className = 'poi-classify-dialog';
    dialog.innerHTML = `
      <div class="poi-classify-sheet">
        <div class="poi-classify-head">
          <div><p class="eyebrow">EVENTO SELECIONADO</p><strong id="poiClassifyTitle">Classificar evento</strong><span id="poiClassifyMeta"></span></div>
          <button type="button" class="icon-button" id="poiClassifyClose" aria-label="Fechar">×</button>
        </div>
        <div class="poi-classify-actions">
          <button type="button" class="poi-classify-action" id="poiClassifyIdentify"><span>◎</span><div><strong>Identificar / corrigir pessoa</strong><small>Usa a mesma correção manual da Timeline tradicional.</small></div><b>›</b></button>
          <button type="button" class="poi-classify-action danger" id="poiClassifyFalsePositive"><span>⊘</span><div><strong>Marcar como falso positivo</strong><small>Ensina a memória negativa e impede novos Pushes semelhantes.</small></div><b>›</b></button>
        </div>
        <button type="button" class="button ghost poi-classify-cancel" id="poiClassifyCancel">Cancelar</button>
      </div>`;
    document.body.appendChild(dialog);

    document.getElementById('poiClassifyClose')?.addEventListener('click', closeClassifyDialog);
    document.getElementById('poiClassifyCancel')?.addEventListener('click', closeClassifyDialog);
    dialog.addEventListener('click', event => { if (event.target === dialog) closeClassifyDialog(); });
    document.getElementById('poiClassifyIdentify')?.addEventListener('click', identifySelectedEvent);
    document.getElementById('poiClassifyFalsePositive')?.addEventListener('click', toggleSelectedFalsePositive);
  }

  function openClassifyDialog(eventId) {
    const id = Number(eventId || V61.selectedEventId || selectedFromDom());
    if (!id) {
      if (typeof toast === 'function') toast('Selecione primeiro um evento na Timeline.', 'error');
      return;
    }
    V61.selectedEventId = id;
    syncSelection(id, { scrollCard: true });
    const info = cardInfo(id);
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    if (!dialog) return;
    dialog.dataset.eventId = String(id);
    dialog.dataset.falsePositive = info.isFalsePositive ? '1' : '0';
    const title = document.getElementById('poiClassifyTitle');
    const meta = document.getElementById('poiClassifyMeta');
    const fp = document.getElementById('poiClassifyFalsePositive');
    if (title) title.textContent = info.label;
    if (meta) meta.textContent = `${info.time || 'horário selecionado'} · evento #${id}`;
    if (fp) {
      fp.classList.toggle('restore', info.isFalsePositive);
      fp.querySelector('strong').textContent = info.isFalsePositive ? 'Restaurar detecção' : 'Marcar como falso positivo';
      fp.querySelector('small').textContent = info.isFalsePositive
        ? 'Retira este evento da memória negativa e volta a permitir sua classificação.'
        : 'Ensina a memória negativa e impede novos Pushes semelhantes.';
    }
    try { dialog.showModal(); }
    catch (_) { dialog.setAttribute('open', ''); }
  }

  async function refreshTimelines() {
    const refresh = document.getElementById('poiTimelineRefresh');
    refresh?.click();
    try {
      if (typeof loadEvents === 'function') await loadEvents();
    } catch (_) {}
  }

  async function identifySelectedEvent() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const id = Number(dialog?.dataset.eventId || V61.selectedEventId || 0);
    if (!id) return;
    const info = cardInfo(id);
    const generic = ['pessoa', 'falso positivo', 'desconhecido'];
    const suggested = generic.includes(info.label.toLowerCase()) ? '' : info.label.replace(/\?$/, '');
    const name = prompt('Quem é esta pessoa? A correção manual tem prioridade sobre o ReID automático.', suggested);
    if (!name?.trim()) return;
    try {
      const result = await api(`/api/identity/events/${id}/assign`, {
        method: 'POST',
        body: JSON.stringify({ name: name.trim() }),
      });
      if (typeof toast === 'function') toast(`${result.person_name || name.trim()} associado ao evento.`);
      closeClassifyDialog();
      await refreshTimelines();
      setTimeout(() => syncSelection(id, { scrollCard: true }), 500);
    } catch (error) {
      if (typeof toast === 'function') toast(`Classificação: ${error.message}`, 'error');
    }
  }

  async function toggleSelectedFalsePositive() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const id = Number(dialog?.dataset.eventId || V61.selectedEventId || 0);
    if (!id) return;
    const isFalsePositive = dialog?.dataset.falsePositive === '1';
    const next = !isFalsePositive;
    const message = next
      ? 'Marcar este evento como falso positivo? Ele será usado como exemplo manual da memória negativa e deixará de gerar Push.'
      : 'Restaurar este evento? Ele deixará de ser tratado como falso positivo.';
    if (!confirm(message)) return;
    try {
      await api(`/api/events/${id}/false-positive?value=${next ? 'true' : 'false'}`, { method: 'PATCH' });
      if (typeof toast === 'function') toast(next ? 'Falso positivo aprendido.' : 'Evento restaurado.');
      closeClassifyDialog();
      if (next && !document.getElementById('poiTimelineShowFp')?.checked) V61.selectedEventId = null;
      await refreshTimelines();
      setTimeout(() => syncSelection(V61.selectedEventId, { scrollCard: true }), 500);
    } catch (error) {
      if (typeof toast === 'function') toast(`Falso positivo: ${error.message}`, 'error');
    }
  }

  function installStageClassify() {
    const stage = document.getElementById('poiTimelineStage');
    if (!stage || document.getElementById('poiTimelineClassify')) return Boolean(document.getElementById('poiTimelineClassify'));
    const button = document.createElement('button');
    button.id = 'poiTimelineClassify';
    button.type = 'button';
    button.className = 'poi-stage-classify';
    button.hidden = true;
    button.innerHTML = '<span>⋯</span><strong>Classificar evento</strong>';
    button.addEventListener('click', event => {
      event.stopPropagation();
      openClassifyDialog(Number(button.dataset.eventId || V61.selectedEventId || 0));
    });
    stage.appendChild(button);

    document.getElementById('poiTimelineSnapshot')?.addEventListener('click', () => {
      if (V61.selectedEventId) openClassifyDialog(V61.selectedEventId);
    });
    return true;
  }

  function bindSelectionSync() {
    if (document.documentElement.dataset.poiV61Bound === '1') return;
    document.documentElement.dataset.poiV61Bound = '1';

    document.addEventListener('click', event => {
      const marker = event.target.closest?.('#poiEventMarkers [data-event-id]');
      const card = event.target.closest?.('#poiEventStrip [data-event-card]');
      if (!marker && !card) return;
      const id = Number(marker?.dataset.eventId || card?.dataset.eventCard || 0);
      if (!id) return;
      V61.selectedEventId = id;
      requestAnimationFrame(() => syncSelection(id, { scrollCard: Boolean(marker) }));
    });

    const strip = document.getElementById('poiEventStrip');
    if (strip && !V61.observer) {
      V61.observer = new MutationObserver(() => {
        const selected = selectedFromDom();
        if (selected) V61.selectedEventId = selected;
        if (V61.selectedEventId && eventCard(V61.selectedEventId)) syncSelection(V61.selectedEventId, { scrollCard: false });
        else updateClassifyButton();
      });
      V61.observer.observe(strip, { childList: true, subtree: true });
    }
  }

  function install() {
    if (!document.getElementById('poiTimelinePlayer')) return false;
    installClassifyDialog();
    installStageClassify();
    bindSelectionSync();
    const selected = selectedFromDom();
    if (selected) syncSelection(selected, { scrollCard: false });
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (install() || attempts > 60) clearInterval(timer);
    }, 100);
  }
})();