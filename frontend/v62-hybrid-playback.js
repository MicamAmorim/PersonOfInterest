(() => {
  const H = {
    data: null,
    key: '',
    playing: false,
    transitioning: false,
    slideTimer: null,
    speed: 1,
    selectedEventId: null,
    lastHighlightedId: null,
    loadToken: 0,
  };

  const q = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function timelineActive() {
    return Boolean(document.getElementById('timelineView')?.classList.contains('active'));
  }

  function cameraId() {
    return Number(document.getElementById('poiTimelineCamera')?.value || 0) || null;
  }

  function dateValue() {
    return document.getElementById('poiTimelineDate')?.value || '';
  }

  function visibleEvents() {
    const events = H.data?.events || [];
    const showFp = Boolean(document.getElementById('poiTimelineShowFp')?.checked);
    return showFp ? events : events.filter(item => item.identity_state !== 'false_positive');
  }

  function currentSecond() {
    return Number(document.getElementById('poiDayScrubber')?.value || 0) || 0;
  }

  function setPlaying(value) {
    H.playing = Boolean(value);
    const play = document.getElementById('poiHybridPlay');
    const center = document.getElementById('poiHybridCenterPlay');
    if (play) {
      play.textContent = H.playing ? '❚❚' : '▶';
      play.title = H.playing ? 'Pausar (Espaço)' : 'Reproduzir (Espaço)';
      play.setAttribute('aria-label', play.title);
    }
    if (center) {
      center.textContent = H.playing ? '❚❚' : '▶';
      center.classList.toggle('playing', H.playing);
      center.setAttribute('aria-label', H.playing ? 'Pausar Timeline' : 'Reproduzir Timeline');
    }
    const status = document.getElementById('poiHybridStatus');
    if (status) status.textContent = H.playing ? 'Reproduzindo sequência temporal' : 'Pausado';
  }

  function clearSlideTimer() {
    if (H.slideTimer) clearTimeout(H.slideTimer);
    H.slideTimer = null;
  }

  function playbackRate() {
    return Math.max(.25, Math.min(4, Number(H.speed) || 1));
  }

  async function loadDayData(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && H.data && H.key === key) return H.data;
    const token = ++H.loadToken;
    const offset = -new Date().getTimezoneOffset();
    try {
      const data = await api(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`);
      if (token !== H.loadToken) return H.data;
      H.data = data;
      H.key = key;
      return data;
    } catch (error) {
      if (typeof toast === 'function') toast(`Reprodução: ${error.message}`, 'error');
      return null;
    }
  }

  function playableRecordings() {
    return (H.data?.recordings || []).filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second));
  }

  function recordingAt(second, preferredEventId = null) {
    const records = playableRecordings().filter(rec => Number(rec.start_second) <= second && second <= Number(rec.end_second));
    if (preferredEventId) {
      const exact = records.find(rec => Number(rec.source_event_id) === Number(preferredEventId));
      if (exact) return exact;
    }
    return records.find(rec => rec.mode === 'event') || records[0] || null;
  }

  function eventAt(second, tolerance = 15) {
    const events = visibleEvents();
    let best = null;
    let delta = Infinity;
    for (const event of events) {
      const d = Math.abs(Number(event.second || 0) - second);
      if (d < delta) { best = event; delta = d; }
    }
    return delta <= tolerance ? best : null;
  }

  function mediaItems() {
    const recordings = playableRecordings().map(rec => ({
      type: 'video',
      start: Number(rec.start_second || 0),
      end: Number(rec.end_second || 0),
      recording: rec,
      eventId: rec.source_event_id ? Number(rec.source_event_id) : null,
    }));
    const snapshots = visibleEvents()
      .filter(event => event.snapshot_url)
      .filter(event => !recordingAt(Number(event.second || 0), event.id))
      .map(event => ({
        type: 'snapshot',
        start: Number(event.second || 0),
        end: Number(event.second || 0),
        event,
        eventId: Number(event.id),
      }));
    return [...recordings, ...snapshots].sort((a, b) => a.start - b.start || (a.type === 'video' ? -1 : 1));
  }

  function nextMedia(afterSecond, inclusive = false) {
    const eps = inclusive ? 0 : .05;
    return mediaItems().find(item => item.end >= afterSecond + eps && (item.start >= afterSecond + eps || (item.type === 'video' && item.start <= afterSecond && item.end > afterSecond + eps))) || null;
  }

  function previousMedia(beforeSecond) {
    const items = mediaItems().filter(item => item.start < beforeSecond - .05);
    return items.length ? items[items.length - 1] : null;
  }

  function syncSelectedEvent(eventId, scroll = true) {
    const id = Number(eventId || 0) || null;
    H.selectedEventId = id;
    document.querySelectorAll('#poiEventStrip [data-event-card]').forEach(card => {
      card.classList.toggle('selected', id != null && Number(card.dataset.eventCard) === id);
    });
    document.querySelectorAll('#poiEventMarkers [data-event-id]').forEach(marker => {
      marker.classList.toggle('selected', id != null && Number(marker.dataset.eventId) === id);
    });
    if (id && scroll) {
      const card = document.querySelector(`#poiEventStrip [data-event-card="${id}"]`);
      const strip = document.getElementById('poiEventStrip');
      if (card && strip) {
        const target = card.offsetLeft - strip.clientWidth / 2 + card.offsetWidth / 2;
        strip.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
      }
    }
    const classify = document.getElementById('poiTimelineClassify');
    if (classify) {
      classify.hidden = !id;
      if (id) classify.dataset.eventId = String(id);
    }
  }

  function syncEventNearNeedle(second, scroll = false) {
    const event = eventAt(second, 2.0);
    if (!event || Number(event.id) === Number(H.lastHighlightedId)) return;
    H.lastHighlightedId = Number(event.id);
    syncSelectedEvent(event.id, scroll);
  }

  function dispatchSeek(second) {
    const scrubber = document.getElementById('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || H.data?.day_duration_seconds || 86400);
    const value = Math.max(0, Math.min(max, Number(second) || 0));
    H.transitioning = true;
    scrubber.value = String(Math.round(value));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
    setTimeout(() => { H.transitioning = false; }, 350);
  }

  function waitAndPlayVideo() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video || video.hidden) return false;
    video.playbackRate = playbackRate();
    const attempt = () => {
      if (!H.playing || video.hidden) return;
      video.playbackRate = playbackRate();
      video.play().catch(() => {
        video.addEventListener('canplay', () => {
          if (H.playing && !video.hidden) video.play().catch(() => {});
        }, { once: true });
      });
    };
    setTimeout(attempt, 60);
    return true;
  }

  function scheduleSnapshotAdvance(second) {
    clearSlideTimer();
    if (!H.playing) return;
    const duration = Math.max(600, 2200 / playbackRate());
    H.slideTimer = setTimeout(() => advanceAfter(second), duration);
  }

  async function showItem(item, offsetSecond = null) {
    if (!item) { pauseSequence(); return; }
    const target = offsetSecond != null ? Number(offsetSecond) : Number(item.start || 0);
    if (item.eventId) syncSelectedEvent(item.eventId, true);
    dispatchSeek(target);
    await new Promise(resolve => setTimeout(resolve, 90));
    if (!H.playing) return;
    if (item.type === 'video') {
      if (!waitAndPlayVideo()) {
        setTimeout(() => { if (H.playing) waitAndPlayVideo(); }, 220);
      }
    } else {
      scheduleSnapshotAdvance(target);
    }
  }

  async function playFromNeedle() {
    clearSlideTimer();
    await loadDayData(false);
    if (!H.data) return;
    setPlaying(true);
    const second = currentSecond();
    const selectedId = H.selectedEventId || Number(document.querySelector('#poiEventStrip .poi-event-card.selected')?.dataset.eventCard || 0) || null;
    const rec = recordingAt(second, selectedId);
    if (rec) {
      await showItem({ type: 'video', start: Number(rec.start_second), end: Number(rec.end_second), recording: rec, eventId: rec.source_event_id || selectedId }, second);
      return;
    }
    const event = selectedId ? visibleEvents().find(item => Number(item.id) === Number(selectedId)) : eventAt(second, 15);
    if (event?.snapshot_url && !recordingAt(Number(event.second || 0), event.id)) {
      await showItem({ type: 'snapshot', start: Number(event.second), end: Number(event.second), event, eventId: Number(event.id) }, Number(event.second));
      return;
    }
    const next = nextMedia(second, true);
    if (next) await showItem(next, next.start);
    else pauseSequence();
  }

  function pauseSequence() {
    clearSlideTimer();
    setPlaying(false);
    const video = document.getElementById('poiTimelineVideo');
    if (video && !video.hidden) {
      try { video.pause(); } catch (_) {}
    }
  }

  function togglePlayback() {
    if (H.playing) pauseSequence();
    else playFromNeedle();
  }

  async function advanceAfter(second) {
    if (!H.playing) return;
    await loadDayData(false);
    const next = nextMedia(Number(second) + .05, false);
    if (next) await showItem(next, next.start);
    else pauseSequence();
  }

  async function seekRelative(delta) {
    await loadDayData(false);
    const target = Math.max(0, currentSecond() + Number(delta || 0));
    dispatchSeek(target);
    const event = eventAt(target, 2);
    if (event) syncSelectedEvent(event.id, true);
    if (H.playing) setTimeout(playFromNeedle, 100);
  }

  async function jumpMedia(direction) {
    await loadDayData(false);
    const second = currentSecond();
    const item = direction < 0 ? previousMedia(second) : nextMedia(second, false);
    if (!item) return;
    dispatchSeek(item.start);
    if (item.eventId) syncSelectedEvent(item.eventId, true);
    if (H.playing) setTimeout(playFromNeedle, 100);
  }

  function installControls() {
    const stage = document.getElementById('poiTimelineStage');
    if (!stage || document.getElementById('poiHybridControls')) return false;

    const center = document.createElement('button');
    center.id = 'poiHybridCenterPlay';
    center.type = 'button';
    center.className = 'poi-hybrid-center-play';
    center.textContent = '▶';
    center.setAttribute('aria-label', 'Reproduzir Timeline');
    center.addEventListener('click', event => { event.stopPropagation(); togglePlayback(); });
    stage.appendChild(center);

    const controls = document.createElement('div');
    controls.id = 'poiHybridControls';
    controls.className = 'poi-hybrid-controls';
    controls.innerHTML = `
      <div class="poi-hybrid-buttons">
        <button type="button" id="poiHybridPrev" title="Mídia anterior">⏮</button>
        <button type="button" id="poiHybridBack" title="Voltar 10 segundos">↶ <span>10</span></button>
        <button type="button" id="poiHybridPlay" class="primary" title="Reproduzir (Espaço)">▶</button>
        <button type="button" id="poiHybridForward" title="Avançar 10 segundos"><span>10</span> ↷</button>
        <button type="button" id="poiHybridNext" title="Próxima mídia">⏭</button>
      </div>
      <div class="poi-hybrid-meta"><span id="poiHybridStatus">Pausado</span><label>Velocidade <select id="poiHybridSpeed"><option value="0.5">0,5×</option><option value="1" selected>1×</option><option value="1.5">1,5×</option><option value="2">2×</option></select></label></div>`;
    stage.insertAdjacentElement('afterend', controls);

    document.getElementById('poiHybridPrev')?.addEventListener('click', () => jumpMedia(-1));
    document.getElementById('poiHybridBack')?.addEventListener('click', () => seekRelative(-10));
    document.getElementById('poiHybridPlay')?.addEventListener('click', togglePlayback);
    document.getElementById('poiHybridForward')?.addEventListener('click', () => seekRelative(10));
    document.getElementById('poiHybridNext')?.addEventListener('click', () => jumpMedia(1));
    document.getElementById('poiHybridSpeed')?.addEventListener('change', event => {
      H.speed = Number(event.target.value) || 1;
      const video = document.getElementById('poiTimelineVideo');
      if (video) video.playbackRate = playbackRate();
      if (H.playing && !document.getElementById('poiTimelineSnapshot')?.hidden) scheduleSnapshotAdvance(currentSecond());
    });
    return true;
  }

  function bindVideoLifecycle() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video || video.dataset.poiHybridBound === '1') return;
    video.dataset.poiHybridBound = '1';
    video.addEventListener('play', () => {
      if (!H.transitioning) setPlaying(true);
      video.playbackRate = playbackRate();
    });
    video.addEventListener('pause', () => {
      if (!H.transitioning && !video.ended && H.playing) setPlaying(false);
    });
    video.addEventListener('timeupdate', () => {
      if (!H.playing) return;
      syncEventNearNeedle(currentSecond(), false);
    });
    video.addEventListener('ended', () => {
      if (!H.playing) return;
      const second = currentSecond();
      const rec = recordingAt(second);
      const records = playableRecordings().filter(item => item.mode === 'continuous');
      if (rec?.mode === 'continuous') {
        const idx = records.findIndex(item => Number(item.id) === Number(rec.id));
        const next = idx >= 0 ? records[idx + 1] : null;
        if (next && Number(next.start_second) - Number(rec.end_second) <= 120) return; // V60 already chains adjacent segments.
      }
      setTimeout(() => advanceAfter(second), 120);
    });
  }

  function bindTimelineInteractions() {
    document.addEventListener('click', event => {
      const marker = event.target.closest?.('#poiEventMarkers [data-event-id]');
      const card = event.target.closest?.('#poiEventStrip [data-event-card]');
      if (!marker && !card) return;
      const id = Number(marker?.dataset.eventId || card?.dataset.eventCard || 0);
      if (!id) return;
      H.selectedEventId = id;
      setTimeout(async () => {
        await loadDayData(false);
        const item = visibleEvents().find(entry => Number(entry.id) === id);
        if (!item) return;
        syncSelectedEvent(id, Boolean(marker));
        dispatchSeek(Number(item.second || 0));
        setTimeout(() => {
          setPlaying(true);
          playFromNeedle();
        }, 100);
      }, 0);
    });

    const scrubber = document.getElementById('poiDayScrubber');
    scrubber?.addEventListener('input', () => {
      if (!H.transitioning) {
        clearSlideTimer();
        syncEventNearNeedle(currentSecond(), false);
      }
    });
    scrubber?.addEventListener('change', () => {
      if (!H.transitioning && H.playing) setTimeout(playFromNeedle, 80);
    });

    ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => {
      document.getElementById(id)?.addEventListener('change', () => {
        pauseSequence();
        H.data = null;
        H.key = '';
        H.selectedEventId = null;
        H.lastHighlightedId = null;
        setTimeout(() => loadDayData(true), 200);
      });
    });
    document.getElementById('poiTimelineRefresh')?.addEventListener('click', () => setTimeout(() => loadDayData(true), 120));
    document.getElementById('poiTimelineShowFp')?.addEventListener('change', () => setTimeout(() => loadDayData(true), 120));

    document.addEventListener('keydown', event => {
      if (event.code !== 'Space' || event.repeat || !timelineActive()) return;
      const target = event.target;
      const tag = String(target?.tagName || '').toLowerCase();
      if (['input', 'textarea', 'select', 'button'].includes(tag) || target?.isContentEditable) return;
      if (document.querySelector('dialog[open]')) return;
      event.preventDefault();
      togglePlayback();
    });
  }

  function installPersonPicker() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const identify = document.getElementById('poiClassifyIdentify');
    if (!dialog || !identify || document.getElementById('poiClassifyPersonPicker')) return false;
    const picker = document.createElement('div');
    picker.id = 'poiClassifyPersonPicker';
    picker.className = 'poi-classify-person-picker';
    picker.hidden = true;
    picker.innerHTML = `
      <div class="poi-person-picker-head"><strong>Quem é esta pessoa?</strong><span>Escolha alguém já cadastrado ou crie um novo nome.</span></div>
      <label>Pessoa<select id="poiClassifyPersonSelect"><option value="">Carregando…</option></select></label>
      <label id="poiClassifyNewNameLabel" hidden>Novo nome<input id="poiClassifyNewName" maxlength="120" autocomplete="off" placeholder="Nome da pessoa"></label>
      <div class="poi-person-picker-actions"><button type="button" class="button ghost" id="poiClassifyPersonBack">Voltar</button><button type="button" class="button primary" id="poiClassifyPersonSave">Salvar identificação</button></div>`;
    dialog.querySelector('.poi-classify-actions')?.insertAdjacentElement('afterend', picker);

    identify.addEventListener('click', async event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const select = document.getElementById('poiClassifyPersonSelect');
      picker.hidden = false;
      dialog.querySelector('.poi-classify-actions').hidden = true;
      document.getElementById('poiClassifyCancel').hidden = true;
      if (select) select.innerHTML = '<option value="">Carregando…</option>';
      let persons = [];
      try {
        if (typeof loadPersons === 'function') await loadPersons();
        persons = Array.isArray(window.state?.persons) ? window.state.persons : [];
        if (!persons.length) persons = await api('/api/persons');
      } catch (_) { persons = Array.isArray(window.state?.persons) ? window.state.persons : []; }
      if (select) {
        select.innerHTML = `${persons.map(person => `<option value="${Number(person.id)}">${q(person.name)}</option>`).join('')}<option value="new">＋ Novo nome…</option>`;
        const title = document.getElementById('poiClassifyTitle')?.textContent?.replace(/\?$/, '').trim().toLowerCase();
        const match = persons.find(person => String(person.name || '').trim().toLowerCase() === title);
        select.value = match ? String(match.id) : (persons.length ? String(persons[0].id) : 'new');
        select.dispatchEvent(new Event('change'));
      }
    }, true);

    document.getElementById('poiClassifyPersonSelect')?.addEventListener('change', event => {
      const isNew = event.target.value === 'new';
      const label = document.getElementById('poiClassifyNewNameLabel');
      if (label) label.hidden = !isNew;
      if (isNew) setTimeout(() => document.getElementById('poiClassifyNewName')?.focus(), 0);
    });
    document.getElementById('poiClassifyPersonBack')?.addEventListener('click', () => {
      picker.hidden = true;
      dialog.querySelector('.poi-classify-actions').hidden = false;
      document.getElementById('poiClassifyCancel').hidden = false;
    });
    document.getElementById('poiClassifyPersonSave')?.addEventListener('click', async () => {
      const eventId = Number(dialog.dataset.eventId || H.selectedEventId || 0);
      const select = document.getElementById('poiClassifyPersonSelect');
      if (!eventId || !select) return;
      const payload = {};
      if (select.value === 'new') {
        const name = document.getElementById('poiClassifyNewName')?.value?.trim();
        if (!name) { if (typeof toast === 'function') toast('Informe o novo nome.', 'error'); return; }
        payload.name = name;
      } else {
        const personId = Number(select.value || 0);
        if (!personId) { if (typeof toast === 'function') toast('Selecione uma pessoa.', 'error'); return; }
        payload.person_id = personId;
      }
      try {
        const result = await api(`/api/identity/events/${eventId}/assign`, { method: 'POST', body: JSON.stringify(payload) });
        if (typeof toast === 'function') toast(`${result.person_name || 'Pessoa'} associado ao evento.`);
        try { dialog.close(); } catch (_) { dialog.removeAttribute('open'); }
        if (typeof loadPersons === 'function') await loadPersons();
        if (typeof loadEvents === 'function') await loadEvents();
        document.getElementById('poiTimelineRefresh')?.click();
        H.data = null;
        H.key = '';
        setTimeout(async () => {
          await loadDayData(true);
          syncSelectedEvent(eventId, true);
        }, 350);
      } catch (error) {
        if (typeof toast === 'function') toast(`Classificação: ${error.message}`, 'error');
      }
    });
    return true;
  }

  async function init() {
    if (!document.getElementById('poiTimelinePlayer')) return false;
    installControls();
    bindVideoLifecycle();
    bindTimelineInteractions();
    installPersonPicker();
    await loadDayData(false);
    return true;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      let attempts = 0;
      const timer = setInterval(() => {
        attempts += 1;
        if (document.getElementById('poiTimelinePlayer')) {
          clearInterval(timer);
          init();
        } else if (attempts > 80) clearInterval(timer);
      }, 100);
    }, { once: true });
  } else {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (document.getElementById('poiTimelinePlayer')) {
        clearInterval(timer);
        init();
      } else if (attempts > 80) clearInterval(timer);
    }, 100);
  }
})();