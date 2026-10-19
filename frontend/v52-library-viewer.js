(() => {
  const viewer = {
    people: [],
    personId: null,
    references: [],
    filtered: [],
    index: 0,
    type: 'all',
    state: 'all',
    key: null,
  };

  const collapseKey = 'poi.v5.people.collapsed';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const pct = value => `${Math.round((Number(value) || 0) * 100)}%`;
  const when = raw => { const d = new Date(raw); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-BR'); };
  const refKey = item => `${item.ref_kind}:${item.id}`;

  function ensureCollapse() {
    const panel = document.getElementById('v5PeoplePanel');
    if (!panel) return false;
    const actions = panel.querySelector('.v5-people-header .identity-actions');
    if (!actions) return false;
    let button = document.getElementById('v5LibraryCollapse');
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.id = 'v5LibraryCollapse';
      button.className = 'button ghost small';
      actions.prepend(button);
      button.addEventListener('click', () => {
        const collapsed = !panel.classList.contains('v5-library-collapsed');
        setCollapsed(collapsed);
      });
    }
    setCollapsed(localStorage.getItem(collapseKey) === '1', false);
    return true;
  }

  function setCollapsed(collapsed, persist = true) {
    const panel = document.getElementById('v5PeoplePanel');
    const button = document.getElementById('v5LibraryCollapse');
    if (!panel || !button) return;
    panel.classList.toggle('v5-library-collapsed', collapsed);
    button.textContent = collapsed ? '▸ Expandir' : '▾ Recolher';
    button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    button.title = collapsed ? 'Expandir Biblioteca de pessoas' : 'Recolher Biblioteca de pessoas';
    if (persist) localStorage.setItem(collapseKey, collapsed ? '1' : '0');
  }

  function ensureViewer() {
    if (document.getElementById('v52ReferenceViewer')) return;
    const root = document.createElement('div');
    root.id = 'v52ReferenceViewer';
    root.className = 'v52-viewer';
    root.hidden = true;
    root.innerHTML = `
      <div class="v52-backdrop" data-v52-close></div>
      <section class="v52-dialog" role="dialog" aria-modal="true" aria-label="Visualizador de referências">
        <header class="v52-toolbar">
          <div class="v52-filter-group">
            <label>Pessoa<select id="v52PersonFilter"></select></label>
            <label>Tipo<select id="v52TypeFilter"><option value="all">Face + Body</option><option value="face">Faces</option><option value="body">Bodies</option></select></label>
            <label>Estado<select id="v52StateFilter"><option value="all">Todos</option><option value="trusted">Confiáveis</option><option value="quarantine">Quarentena</option><option value="disabled">Desativadas</option></select></label>
          </div>
          <div class="v52-toolbar-actions">
            <span id="v52Counter" class="muted"></span>
            <button class="button ghost small" type="button" data-v52-close>Fechar ×</button>
          </div>
        </header>
        <div class="v52-stage">
          <button class="v52-nav prev" type="button" id="v52Prev" aria-label="Referência anterior">‹</button>
          <div class="v52-image-wrap"><img id="v52Image" alt="Referência ampliada"><div id="v52Empty" class="v52-empty" hidden>Nenhuma referência para este filtro.</div></div>
          <button class="v52-nav next" type="button" id="v52Next" aria-label="Próxima referência">›</button>
        </div>
        <footer class="v52-footer">
          <div id="v52Meta" class="v52-meta"></div>
          <div id="v52Actions" class="v52-actions"></div>
        </footer>
      </section>`;
    document.body.appendChild(root);

    root.querySelectorAll('[data-v52-close]').forEach(el => el.addEventListener('click', closeViewer));
    document.getElementById('v52Prev').addEventListener('click', () => step(-1));
    document.getElementById('v52Next').addEventListener('click', () => step(1));
    document.getElementById('v52PersonFilter').addEventListener('change', async event => {
      viewer.personId = Number(event.target.value);
      viewer.key = null;
      await loadViewerReferences();
    });
    document.getElementById('v52TypeFilter').addEventListener('change', event => {
      viewer.type = event.target.value;
      applyFilters();
    });
    document.getElementById('v52StateFilter').addEventListener('change', event => {
      viewer.state = event.target.value;
      applyFilters();
    });
    document.addEventListener('keydown', event => {
      if (root.hidden) return;
      if (event.key === 'Escape') closeViewer();
      if (event.key === 'ArrowLeft') step(-1);
      if (event.key === 'ArrowRight') step(1);
    });
  }

  async function loadViewerPeople() {
    viewer.people = await api('/api/v5/curation/persons');
    const select = document.getElementById('v52PersonFilter');
    select.innerHTML = viewer.people.map(person => `<option value="${person.id}">${esc(person.name)}</option>`).join('');
    if (viewer.personId && viewer.people.some(person => Number(person.id) === Number(viewer.personId))) select.value = String(viewer.personId);
  }

  async function loadViewerReferences() {
    if (!viewer.personId) return;
    const data = await api(`/api/v5/curation/persons/${viewer.personId}/references`);
    viewer.references = (data.references || []).map(item => ({ ...item, person_id: viewer.personId }));
    applyFilters();
  }

  function applyFilters() {
    const previousKey = viewer.key;
    viewer.filtered = viewer.references.filter(item =>
      (viewer.type === 'all' || item.type === viewer.type) &&
      (viewer.state === 'all' || item.state === viewer.state)
    );
    let index = previousKey ? viewer.filtered.findIndex(item => refKey(item) === previousKey) : -1;
    if (index < 0) index = Math.min(viewer.index, Math.max(0, viewer.filtered.length - 1));
    viewer.index = Math.max(0, index);
    renderViewer();
  }

  function currentItem() {
    return viewer.filtered[viewer.index] || null;
  }

  function step(delta) {
    if (!viewer.filtered.length) return;
    viewer.index = (viewer.index + delta + viewer.filtered.length) % viewer.filtered.length;
    viewer.key = refKey(viewer.filtered[viewer.index]);
    renderViewer();
  }

  function stateText(item) {
    if (item.state === 'disabled') return 'Desativada';
    if (item.state === 'quarantine') return 'Quarentena';
    return 'Confiável';
  }

  function renderViewer() {
    const item = currentItem();
    const image = document.getElementById('v52Image');
    const empty = document.getElementById('v52Empty');
    const meta = document.getElementById('v52Meta');
    const actions = document.getElementById('v52Actions');
    const counter = document.getElementById('v52Counter');
    const prev = document.getElementById('v52Prev');
    const next = document.getElementById('v52Next');
    counter.textContent = item ? `${viewer.index + 1} / ${viewer.filtered.length}` : '0 / 0';
    prev.disabled = viewer.filtered.length <= 1;
    next.disabled = viewer.filtered.length <= 1;
    if (!item) {
      image.removeAttribute('src');
      image.hidden = true;
      empty.hidden = false;
      meta.innerHTML = '';
      actions.innerHTML = '';
      viewer.key = null;
      return;
    }
    viewer.key = refKey(item);
    image.hidden = false;
    empty.hidden = true;
    image.src = item.image_url || '';
    const person = viewer.people.find(person => Number(person.id) === Number(viewer.personId));
    const support = item.temporal_support ? ` · ${item.temporal_support} observações` : '';
    const stability = item.stability != null ? ` · estabilidade ${pct(item.stability)}` : '';
    meta.innerHTML = `<strong>${esc(person?.name || '')} · ${item.type === 'face' ? 'Face' : 'Body'} · ${stateText(item)}</strong><span>${esc(item.source || 'histórico')} · qualidade ${pct(item.quality)}${support}${stability}</span><span>${when(item.created_at)}${item.event_id ? ` · evento #${item.event_id}` : ''}</span>`;
    actions.innerHTML = `
      ${item.state === 'quarantine' && item.ref_kind === 'body-event' ? '<button class="button ghost small positive" data-v52-trust>Confiar</button>' : ''}
      <button class="button ghost small" data-v52-toggle>${item.active ? 'Desativar' : 'Ativar'}</button>
      <button class="button ghost small" data-v52-move>Mover para…</button>
      <button class="button ghost small danger" data-v52-delete>Excluir</button>`;
    actions.querySelector('[data-v52-toggle]')?.addEventListener('click', toggleCurrent);
    actions.querySelector('[data-v52-trust]')?.addEventListener('click', trustCurrent);
    actions.querySelector('[data-v52-move]')?.addEventListener('click', moveCurrent);
    actions.querySelector('[data-v52-delete]')?.addEventListener('click', deleteCurrent);
  }

  async function refreshAfterMutation(preferredKey = null) {
    viewer.key = preferredKey;
    await loadViewerReferences();
    document.getElementById('v5PeopleRefresh')?.click();
  }

  async function toggleCurrent() {
    const item = currentItem();
    if (!item) return;
    try {
      await api(`/api/v5/curation/persons/${viewer.personId}/references/${item.ref_kind}/${item.id}/state`, {
        method: 'PATCH',
        body: JSON.stringify({ active: !item.active }),
      });
      toast(item.active ? 'Referência desativada.' : 'Referência ativada.');
      await refreshAfterMutation(refKey(item));
    } catch (error) { toast(error.message, 'error'); }
  }

  async function trustCurrent() {
    const item = currentItem();
    if (!item) return;
    if (!confirm('Confirmar que este corpo pertence a esta pessoa e usá-lo no Body ReID?')) return;
    try {
      await api(`/api/v5/curation/persons/${viewer.personId}/references/${item.ref_kind}/${item.id}/state`, {
        method: 'PATCH',
        body: JSON.stringify({ trusted: true }),
      });
      toast('Body promovido para referência confiável.');
      await refreshAfterMutation(refKey(item));
    } catch (error) { toast(error.message, 'error'); }
  }

  async function moveCurrent() {
    const item = currentItem();
    if (!item) return;
    if (!viewer.people.length) await loadViewerPeople();
    const candidates = viewer.people.filter(person => Number(person.id) !== Number(viewer.personId));
    if (!candidates.length) { toast('Cadastre outra pessoa antes de mover a referência.', 'error'); return; }
    const options = candidates.map(person => `${person.id}: ${person.name}`).join('\n');
    const raw = prompt(`Mover esta referência para quem?\n${options}`, String(candidates[0].id));
    if (raw === null) return;
    const target = candidates.find(person => Number(person.id) === Number(raw));
    if (!target) { toast('Pessoa de destino inválida.', 'error'); return; }
    let syncEvent = false;
    if (item.event_id) {
      syncEvent = confirm(`Esta referência veio do evento #${item.event_id}.\n\nOK: corrigir também o evento para ${target.name}.\nCancelar: mover somente a referência e preservar o histórico.`);
    }
    if (!confirm(`Confirmar reatribuição para ${target.name}${syncEvent ? ' e correção do evento' : ''}?`)) return;
    try {
      await api(`/api/v5/curation/persons/${viewer.personId}/references/${item.ref_kind}/${item.id}/move`, {
        method: 'POST',
        body: JSON.stringify({ target_person_id: target.id, sync_event: syncEvent }),
      });
      toast(syncEvent ? `Referência e evento movidos para ${target.name}.` : `Referência movida para ${target.name}.`);
      await loadViewerPeople();
      await refreshAfterMutation(null);
      if (!viewer.filtered.length) {
        viewer.personId = Number(target.id);
        document.getElementById('v52PersonFilter').value = String(target.id);
        await loadViewerReferences();
      }
    } catch (error) { toast(error.message, 'error'); }
  }

  async function deleteCurrent() {
    const item = currentItem();
    if (!item) return;
    if (!confirm('Excluir definitivamente esta referência? Para apenas ignorá-la no reconhecimento, use Desativar.')) return;
    try {
      await api(`/api/v5/persons/${viewer.personId}/references/${item.ref_kind}/${item.id}`, { method: 'DELETE' });
      toast('Referência excluída.');
      viewer.key = null;
      await refreshAfterMutation(null);
    } catch (error) { toast(error.message, 'error'); }
  }

  async function openViewer(personId, key = null) {
    ensureViewer();
    try {
      viewer.personId = Number(personId);
      viewer.key = key;
      viewer.index = 0;
      await loadViewerPeople();
      document.getElementById('v52PersonFilter').value = String(viewer.personId);
      document.getElementById('v52TypeFilter').value = viewer.type;
      document.getElementById('v52StateFilter').value = viewer.state;
      await loadViewerReferences();
      if (key) {
        const index = viewer.filtered.findIndex(item => refKey(item) === key);
        if (index >= 0) viewer.index = index;
      }
      renderViewer();
      const root = document.getElementById('v52ReferenceViewer');
      root.hidden = false;
      document.body.classList.add('v52-viewer-open');
    } catch (error) { toast(`Viewer: ${error.message}`, 'error'); }
  }

  function closeViewer() {
    const root = document.getElementById('v52ReferenceViewer');
    if (root) root.hidden = true;
    document.body.classList.remove('v52-viewer-open');
  }

  function installImageOpen() {
    document.addEventListener('click', event => {
      const image = event.target.closest?.('.v5-ref-image img');
      if (!image) return;
      const card = image.closest('.v5-ref-card');
      const action = card?.querySelector('[data-v5-toggle-ref]');
      if (!action) return;
      const [pid, kind, id] = action.dataset.v5ToggleRef.split('|');
      event.preventDefault();
      event.stopPropagation();
      openViewer(Number(pid), `${kind}:${id}`);
    }, true);
  }

  function install() {
    ensureViewer();
    installImageOpen();
    if (ensureCollapse()) return;
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (ensureCollapse() || tries > 60) clearInterval(timer);
    }, 150);
  }

  install();
})();
