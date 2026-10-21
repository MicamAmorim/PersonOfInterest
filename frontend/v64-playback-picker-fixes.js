(() => {
  const V64 = { personsLoading: false, personsLoadedAt: 0, personsAttemptAt: 0, pickerTimer: null };

  function timelineActive() {
    return Boolean(document.getElementById('timelineView')?.classList.contains('active'));
  }

  function isTypingTarget(target) {
    const tag = String(target?.tagName || '').toLowerCase();
    return ['input', 'textarea', 'select'].includes(tag) || Boolean(target?.isContentEditable);
  }

  function hybridPlaying() {
    const video = document.getElementById('poiTimelineVideo');
    const button = document.getElementById('poiHybridPlay');
    return Boolean((video && !video.hidden && !video.paused && !video.ended) || button?.textContent?.includes('❚'));
  }

  function toggleHybridPlayback() {
    const button = document.getElementById('poiHybridPlay');
    if (button) button.click();
  }

  function bindSpaceCapture() {
    document.addEventListener('keydown', event => {
      if (event.code !== 'Space' || event.repeat || !timelineActive()) return;
      if (document.querySelector('#poiTimelineClassifyDialog[open], dialog[open]')) return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      toggleHybridPlayback();
    }, true);
  }

  function bindClipAutoplay() {
    document.addEventListener('click', event => {
      const clip = event.target.closest?.('#poiV63ClipTrack [data-v63-clip]');
      if (!clip) return;
      try { clip.blur(); } catch (_) {}
      const eventId = Number(clip.dataset.eventId || 0);
      if (eventId) {
        const card = document.querySelector(`#poiEventStrip [data-event-card="${eventId}"]`);
        if (card) {
          // Reuse the same path as the thumbnail so both interactions seek/play identically.
          card.click();
          return;
        }
      }
      if (!hybridPlaying()) toggleHybridPlayback();
    });
  }

  async function fetchPersons() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(`/api/persons?_=${Date.now()}`, {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      return Array.isArray(payload) ? payload : [];
    } catch (error) {
      if (error?.name === 'AbortError') throw new Error('tempo limite ao buscar pessoas');
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function hasNumericPersonOption(select) {
    return [...select.options].some(option => /^\d+$/.test(option.value) && Number(option.value) > 0);
  }

  function escaped(value = '') {
    return String(value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function currentPersonName() {
    return document.getElementById('poiClassifyTitle')?.textContent?.replace(/\?$/, '').trim() || '';
  }

  async function populatePersonPicker(force = false) {
    const picker = document.getElementById('poiClassifyPersonPicker');
    const select = document.getElementById('poiClassifyPersonSelect');
    if (!picker || !select || picker.hidden || V64.personsLoading) return;
    const loading = /carregando/i.test(select.textContent || '');
    const missingPeople = !hasNumericPersonOption(select);
    if (!force && !loading && !missingPeople && Date.now() - V64.personsLoadedAt < 5000) return;
    if (!force && Date.now() - V64.personsAttemptAt < 1800) return;

    V64.personsAttemptAt = Date.now();
    V64.personsLoading = true;
    const previous = select.value;
    select.disabled = true;
    select.innerHTML = '<option value="">Carregando pessoas…</option>';

    try {
      let persons = await fetchPersons();
      if (!persons.length) {
        try {
          if (typeof state !== 'undefined' && Array.isArray(state.persons)) persons = state.persons;
        } catch (_) {}
      }
      const options = persons
        .filter(person => person && Number(person.id) > 0 && String(person.name || '').trim())
        .sort((a, b) => String(a.name).localeCompare(String(b.name), 'pt-BR'));

      select.innerHTML = '<option value="">Selecione uma pessoa…</option>' +
        options.map(person => `<option value="${Number(person.id)}">${escaped(person.name)}</option>`).join('') +
        '<option value="new">＋ Novo nome…</option>';

      const title = currentPersonName().toLowerCase();
      const titleMatch = options.find(person => String(person.name || '').trim().toLowerCase() === title);
      if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
      else if (titleMatch) select.value = String(titleMatch.id);
      else select.value = '';

      select.dataset.poiV64Ready = options.length ? '1' : 'empty';
      V64.personsLoadedAt = Date.now();
    } catch (error) {
      select.innerHTML = '<option value="">Falha ao carregar pessoas</option><option value="new">＋ Novo nome…</option>';
      select.dataset.poiV64Ready = '0';
      if (typeof toast === 'function') toast(`Pessoas: ${error.message}`, 'error');
    } finally {
      select.disabled = false;
      V64.personsLoading = false;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  async function openPersonPickerDirect() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const picker = document.getElementById('poiClassifyPersonPicker');
    const select = document.getElementById('poiClassifyPersonSelect');
    const actions = dialog?.querySelector('.poi-classify-actions');
    const cancel = document.getElementById('poiClassifyCancel');
    if (!dialog || !picker || !select) return;

    picker.hidden = false;
    if (actions) actions.hidden = true;
    if (cancel) cancel.hidden = true;
    select.innerHTML = '<option value="">Carregando pessoas…</option>';
    select.disabled = true;
    await populatePersonPicker(true);
  }

  function bindPersonPickerDirect() {
    document.addEventListener('click', event => {
      const identify = event.target.closest?.('#poiClassifyIdentify');
      if (!identify) return;
      // Capture on document runs before the old V6.2 listener attached to the button.
      // This bypasses its potentially hanging await loadPersons() path entirely.
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      void openPersonPickerDirect();
    }, true);
  }

  function pickerNeedsRecovery() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const picker = document.getElementById('poiClassifyPersonPicker');
    const select = document.getElementById('poiClassifyPersonSelect');
    if (!dialog?.open || !picker || picker.hidden || !select) return false;
    return /carregando/i.test(select.textContent || '') || !hasNumericPersonOption(select);
  }

  function startPersonPickerRecovery() {
    if (V64.pickerTimer) return;
    V64.pickerTimer = setInterval(() => {
      if (pickerNeedsRecovery()) populatePersonPicker(false);
    }, 1000);
  }

  function hardenVideoFit() {
    const video = document.getElementById('poiTimelineVideo');
    if (!video) return;
    video.style.objectFit = 'contain';
    video.style.objectPosition = 'center center';
  }

  function init() {
    if (!document.getElementById('poiTimelinePlayer')) return false;
    bindSpaceCapture();
    bindClipAutoplay();
    bindPersonPickerDirect();
    startPersonPickerRecovery();
    hardenVideoFit();
    return true;
  }

  function wait() {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (document.getElementById('poiTimelinePlayer') && document.getElementById('poiHybridControls') && document.getElementById('poiClassifyPersonPicker')) {
        clearInterval(timer);
        init();
      } else if (attempts > 120) clearInterval(timer);
    }, 100);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wait, { once: true });
  else wait();
})();
