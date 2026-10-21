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
    const response = await fetch(`/api/persons?_=${Date.now()}`, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    return Array.isArray(payload) ? payload : [];
  }

  function hasNumericPersonOption(select) {
    return [...select.options].some(option => /^\d+$/.test(option.value) && Number(option.value) > 0);
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
        options.map(person => `<option value="${Number(person.id)}">${String(person.name).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}</option>`).join('') +
        '<option value="new">＋ Novo nome…</option>';
      if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
      else select.value = '';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      V64.personsLoadedAt = Date.now();
      select.dataset.poiV64Ready = options.length ? '1' : 'empty';
    } catch (error) {
      select.innerHTML = '<option value="">Falha ao carregar pessoas</option><option value="new">＋ Novo nome…</option>';
      select.dataset.poiV64Ready = '0';
      if (typeof toast === 'function') toast(`Pessoas: ${error.message}`, 'error');
    } finally {
      V64.personsLoading = false;
    }
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
    }, 700);
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
