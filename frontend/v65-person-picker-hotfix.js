(() => {
  const escapeHtml = (value = '') => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  async function fetchPersons(timeoutMs = 5000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
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
      if (!Array.isArray(payload)) throw new Error('Resposta inválida de /api/persons');
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  function pickerElements() {
    const dialog = document.getElementById('poiTimelineClassifyDialog');
    const picker = document.getElementById('poiClassifyPersonPicker');
    const select = document.getElementById('poiClassifyPersonSelect');
    const actions = dialog?.querySelector('.poi-classify-actions');
    const cancel = document.getElementById('poiClassifyCancel');
    return { dialog, picker, select, actions, cancel };
  }

  function openPickerShell() {
    const { picker, select, actions, cancel } = pickerElements();
    if (!picker || !select) return null;
    picker.hidden = false;
    if (actions) actions.hidden = true;
    if (cancel) cancel.hidden = true;
    select.innerHTML = '<option value="">Carregando pessoas…</option>';
    select.disabled = true;
    return select;
  }

  function chooseCurrentPerson(persons) {
    const title = document.getElementById('poiClassifyTitle')?.textContent?.replace(/\?$/, '').trim().toLocaleLowerCase('pt-BR') || '';
    return persons.find(person => String(person.name || '').trim().toLocaleLowerCase('pt-BR') === title) || null;
  }

  async function loadPicker() {
    const select = openPickerShell();
    if (!select) return;
    try {
      const persons = (await fetchPersons())
        .filter(person => Number(person?.id) > 0 && String(person?.name || '').trim())
        .sort((a, b) => String(a.name).localeCompare(String(b.name), 'pt-BR'));

      select.innerHTML = '<option value="">Selecione uma pessoa…</option>' +
        persons.map(person => `<option value="${Number(person.id)}">${escapeHtml(person.name)}</option>`).join('') +
        '<option value="new">＋ Novo nome…</option>';
      select.disabled = false;

      const current = chooseCurrentPerson(persons);
      select.value = current ? String(current.id) : '';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      select.dataset.poiPersonPickerReady = '1';
    } catch (error) {
      const message = error?.name === 'AbortError' ? 'Tempo esgotado ao carregar pessoas' : `Falha ao carregar pessoas${error?.message ? `: ${error.message}` : ''}`;
      select.innerHTML = `<option value="">${escapeHtml(message)}</option><option value="new">＋ Novo nome…</option>`;
      select.disabled = false;
      select.dataset.poiPersonPickerReady = '0';
      if (typeof toast === 'function') toast(message, 'error');
    }
  }

  // Capture on document intentionally runs before the old target listener in v62.
  document.addEventListener('click', event => {
    const identify = event.target.closest?.('#poiClassifyIdentify');
    if (!identify) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    void loadPicker();
  }, true);

  // Defensive recovery for a modal already left in an old "Carregando…" state.
  const recovery = setInterval(() => {
    const { dialog, picker, select } = pickerElements();
    if (!dialog?.open || !picker || picker.hidden || !select) return;
    if (/carregando/i.test(select.textContent || '') && select.dataset.poiPersonPickerLoading !== '1') {
      select.dataset.poiPersonPickerLoading = '1';
      loadPicker().finally(() => { select.dataset.poiPersonPickerLoading = '0'; });
    }
  }, 800);

  window.addEventListener('pagehide', () => clearInterval(recovery), { once: true });
})();
