(() => {
  const V5 = { people: [], opened: new Set() };

  function ensurePanel() {
    const view = document.getElementById('identityView');
    if (!view || document.getElementById('v5PeoplePanel')) return Boolean(document.getElementById('v5PeoplePanel'));
    const panel = document.createElement('section');
    panel.id = 'v5PeoplePanel';
    panel.className = 'panel v5-people-panel';
    panel.innerHTML = `
      <div class="panel-header v5-people-header">
        <div>
          <p class="eyebrow">V5 · IDENTIDADE PERSISTENTE</p>
          <h2>Biblioteca de pessoas</h2>
          <p class="muted paragraph">Face é identidade forte. Corpo é evidência provável agregada no tempo. Referências podem ser confiadas, desativadas ou movidas sem apagar o histórico.</p>
        </div>
        <div class="identity-actions">
          <button class="button ghost small" id="v5PeopleRefresh">↻ Atualizar</button>
          <button class="button primary small" id="v5NewPerson">+ Nova pessoa</button>
        </div>
      </div>
      <div class="v5-architecture-note">
        <span>TRACK persistente</span><b>→</b><span>best face/body/frame</span><b>→</b><span>agregação temporal</span><b>→</b><span>âncoras confiáveis</span><b>→</b><span>evento único</span>
      </div>
      <div id="v5PeopleGrid" class="v5-people-grid"><p class="muted">Carregando pessoas…</p></div>
      <input id="v5ImportFile" type="file" accept="image/*" hidden />`;
    view.prepend(panel);
    document.getElementById('v5PeopleRefresh')?.addEventListener('click', loadPeople);
    document.getElementById('v5NewPerson')?.addEventListener('click', createPerson);
    return true;
  }

  function q(value) { return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
  function pct(value) { return `${Math.round((Number(value) || 0) * 100)}%`; }
  function when(raw) { const d = new Date(raw); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-BR'); }

  async function loadPeople() {
    if (!ensurePanel()) return;
    const grid = document.getElementById('v5PeopleGrid');
    try {
      V5.people = await api('/api/v5/curation/persons');
      if (!V5.people.length) {
        grid.innerHTML = '<div class="empty-state compact"><div class="empty-icon">◎</div><h3>Nenhuma pessoa cadastrada</h3><p>Crie uma pessoa e adicione referências pela câmera ou por imagem.</p></div>';
        return;
      }
      grid.innerHTML = V5.people.map(person => `
        <article class="v5-person-card" data-v5-person="${person.id}">
          <div class="v5-person-main">
            <div class="v5-person-avatar">${q(person.name).slice(0, 1).toUpperCase()}</div>
            <div class="v5-person-name"><strong>${q(person.name)}</strong><span>${person.event_count || 0} evento(s)</span></div>
            <div class="v5-person-metrics">
              <span title="Faces ativas"><b>${person.face_reference_count || 0}</b> face</span>
              <span title="Referências corporais confiáveis"><b>${person.trusted_body_reference_count || 0}</b> body confiável</span>
              <span class="${person.quarantined_body_count ? 'warning' : ''}" title="Bodies aguardando validação"><b>${person.quarantined_body_count || 0}</b> quarentena</span>
              <span class="${person.disabled_reference_count ? 'disabled' : ''}" title="Referências preservadas, mas ignoradas pelo matcher"><b>${person.disabled_reference_count || 0}</b> desativadas</span>
            </div>
          </div>
          <div class="v5-person-actions">
            <button class="button ghost small" data-v5-refs="${person.id}">Referências</button>
            <button class="button ghost small" data-v5-camera="${person.id}">Capturar câmera</button>
            <button class="button ghost small" data-v5-import="${person.id}">Importar imagem</button>
            <button class="button ghost small danger" data-v5-clear="${person.id}">Limpar referências</button>
            <button class="button ghost small danger" data-v5-delete="${person.id}">Excluir pessoa</button>
          </div>
          <div id="v5Refs-${person.id}" class="v5-reference-area" hidden></div>
        </article>`).join('');
      bindPeopleActions();
      for (const id of [...V5.opened]) await loadReferences(id, false);
    } catch (error) {
      grid.innerHTML = `<p class="muted">Falha ao carregar biblioteca: ${q(error.message)}</p>`;
    }
  }

  function bindPeopleActions() {
    document.querySelectorAll('[data-v5-refs]').forEach(el => el.addEventListener('click', () => toggleReferences(Number(el.dataset.v5Refs))));
    document.querySelectorAll('[data-v5-camera]').forEach(el => el.addEventListener('click', () => captureCamera(Number(el.dataset.v5Camera))));
    document.querySelectorAll('[data-v5-import]').forEach(el => el.addEventListener('click', () => importImage(Number(el.dataset.v5Import))));
    document.querySelectorAll('[data-v5-clear]').forEach(el => el.addEventListener('click', () => clearReferences(Number(el.dataset.v5Clear))));
    document.querySelectorAll('[data-v5-delete]').forEach(el => el.addEventListener('click', () => deletePerson(Number(el.dataset.v5Delete))));
  }

  async function createPerson() {
    const name = prompt('Nome da nova pessoa:');
    if (!name?.trim()) return;
    try {
      await api('/api/persons', { method: 'POST', body: JSON.stringify({ name: name.trim() }) });
      toast(`${name.trim()} cadastrado.`);
      await Promise.all([loadPeople(), typeof loadPersons === 'function' ? loadPersons() : Promise.resolve()]);
    } catch (error) { toast(error.message, 'error'); }
  }

  async function toggleReferences(personId) {
    const area = document.getElementById(`v5Refs-${personId}`);
    if (!area) return;
    if (!area.hidden) {
      area.hidden = true;
      V5.opened.delete(personId);
      return;
    }
    area.hidden = false;
    V5.opened.add(personId);
    await loadReferences(personId, true);
  }

  function stateBadge(item) {
    if (item.state === 'disabled') return '<span class="v5-trust disabled">desativada</span>';
    if (item.state === 'quarantine') return '<span class="v5-trust quarantine">quarentena</span>';
    return '<span class="v5-trust trusted">confiável</span>';
  }

  function referenceCard(personId, item) {
    const support = item.temporal_support ? ` · ${item.temporal_support} obs.` : '';
    const stability = item.stability != null ? ` · estabilidade ${pct(item.stability)}` : '';
    const typeLabel = item.type === 'face' ? 'Face' : 'Body';
    const toggleLabel = item.active ? 'Desativar' : 'Ativar';
    const trustAction = item.state === 'quarantine' && item.ref_kind === 'body-event'
      ? `<button class="button ghost tiny positive" data-v5-trust-ref="${personId}|${q(item.ref_kind)}|${item.id}">Confiar</button>`
      : '';
    return `<article class="v5-ref-card ${item.state}">
      <div class="v5-ref-image">${item.image_url ? `<img src="${q(item.image_url)}" loading="lazy" alt="Referência">` : '<span>sem imagem</span>'}</div>
      <div class="v5-ref-meta">
        <strong>${typeLabel} ${stateBadge(item)}</strong>
        <span>${q(item.source || 'histórico')}</span>
        <span>qualidade ${pct(item.quality)}${support}${stability}</span>
        <span>${when(item.created_at)}</span>
      </div>
      <div class="v5-ref-actions">
        ${trustAction}
        <button class="button ghost tiny" data-v5-toggle-ref="${personId}|${q(item.ref_kind)}|${item.id}|${item.active ? '0' : '1'}">${toggleLabel}</button>
        <button class="button ghost tiny" data-v5-move-ref="${personId}|${q(item.ref_kind)}|${item.id}|${item.event_id || ''}">Mover para…</button>
        <button class="button ghost tiny danger" data-v5-remove-ref="${personId}|${q(item.ref_kind)}|${item.id}">Excluir</button>
      </div>
    </article>`;
  }

  function groupBlock(title, subtitle, items, cls) {
    return `<section class="v5-curation-group ${cls}">
      <div class="v5-curation-heading"><div><h4>${title} <span>${items.length}</span></h4><p>${subtitle}</p></div></div>
      <div class="v5-ref-grid">${items.length ? items.map(item => referenceCard(item.person_id || '', item)).join('') : '<p class="muted">Nenhuma referência neste grupo.</p>'}</div>
    </section>`;
  }

  async function loadReferences(personId, showLoading = true) {
    const area = document.getElementById(`v5Refs-${personId}`);
    if (!area || area.hidden) return;
    if (showLoading) area.innerHTML = '<p class="muted">Carregando referências…</p>';
    try {
      const data = await api(`/api/v5/curation/persons/${personId}/references`);
      const trusted = (data.groups.trusted || []).map(item => ({ ...item, person_id: personId }));
      const quarantine = (data.groups.quarantine || []).map(item => ({ ...item, person_id: personId }));
      const disabled = (data.groups.disabled || []).map(item => ({ ...item, person_id: personId }));
      area.innerHTML = [
        groupBlock('Confiáveis', 'Participam da classificação. Faces ativas e bodies validados ficam aqui.', trusted, 'trusted'),
        groupBlock('Quarentena', 'Bodies automáticos preservados, mas ainda fora da galeria positiva. Você pode validar manualmente com “Confiar”.', quarantine, 'quarantine'),
        groupBlock('Desativadas', 'Continuam disponíveis para auditoria, mas são completamente ignoradas pelo matcher.', disabled, 'disabled'),
      ].join('');
      bindReferenceActions(area, personId);
    } catch (error) { area.innerHTML = `<p class="muted">${q(error.message)}</p>`; }
  }

  function bindReferenceActions(area, personId) {
    area.querySelectorAll('[data-v5-toggle-ref]').forEach(el => el.addEventListener('click', async () => {
      const [pid, kind, id, active] = el.dataset.v5ToggleRef.split('|');
      try {
        await api(`/api/v5/curation/persons/${pid}/references/${kind}/${id}/state`, {
          method: 'PATCH', body: JSON.stringify({ active: active === '1' }),
        });
        toast(active === '1' ? 'Referência ativada.' : 'Referência desativada.');
        await Promise.all([loadReferences(Number(pid), false), loadPeople()]);
      } catch (error) { toast(error.message, 'error'); }
    }));

    area.querySelectorAll('[data-v5-trust-ref]').forEach(el => el.addEventListener('click', async () => {
      const [pid, kind, id] = el.dataset.v5TrustRef.split('|');
      if (!confirm('Você confirma manualmente que este corpo pertence a esta pessoa? Ele passará a participar do Body ReID como referência confiável.')) return;
      try {
        await api(`/api/v5/curation/persons/${pid}/references/${kind}/${id}/state`, {
          method: 'PATCH', body: JSON.stringify({ trusted: true }),
        });
        toast('Body validado e promovido para confiável.');
        await Promise.all([loadReferences(Number(pid), false), loadPeople()]);
      } catch (error) { toast(error.message, 'error'); }
    }));

    area.querySelectorAll('[data-v5-move-ref]').forEach(el => el.addEventListener('click', async () => {
      const [pid, kind, id, eventId] = el.dataset.v5MoveRef.split('|');
      await moveReference(Number(pid), kind, Number(id), eventId ? Number(eventId) : null);
    }));

    area.querySelectorAll('[data-v5-remove-ref]').forEach(el => el.addEventListener('click', async () => {
      const [pid, kind, id] = el.dataset.v5RemoveRef.split('|');
      if (!confirm('Excluir definitivamente esta referência? Se você só quer tirá-la da classificação, prefira “Desativar”.')) return;
      try {
        await api(`/api/v5/persons/${pid}/references/${kind}/${id}`, { method: 'DELETE' });
        toast('Referência excluída.');
        await Promise.all([loadReferences(Number(pid), false), loadPeople()]);
      } catch (error) { toast(error.message, 'error'); }
    }));
  }

  async function moveReference(personId, refKind, referenceId, eventId) {
    const candidates = V5.people.filter(person => Number(person.id) !== Number(personId));
    if (!candidates.length) { toast('Cadastre outra pessoa antes de mover a referência.', 'error'); return; }
    const source = V5.people.find(person => Number(person.id) === Number(personId));
    const options = candidates.map(person => `${person.id}: ${person.name}`).join('\n');
    const raw = prompt(`Mover referência de ${source?.name || 'esta pessoa'} para quem?\n${options}`, String(candidates[0].id));
    if (raw === null) return;
    const target = candidates.find(person => Number(person.id) === Number(raw));
    if (!target) { toast('Pessoa de destino inválida.', 'error'); return; }

    let syncEvent = false;
    if (eventId) {
      syncEvent = confirm(
        `Esta referência nasceu do evento #${eventId}.\n\nOK: corrigir também o evento original para ${target.name}.\nCancelar: mover só a referência e preservar a identidade histórica do evento.`
      );
    }
    if (!confirm(`Confirmar a reatribuição para ${target.name}${syncEvent ? ' e corrigir também o evento' : ''}?`)) return;

    try {
      const result = await api(`/api/v5/curation/persons/${personId}/references/${refKind}/${referenceId}/move`, {
        method: 'POST',
        body: JSON.stringify({ target_person_id: target.id, sync_event: syncEvent }),
      });
      toast(syncEvent
        ? `Referência e evento reatribuídos para ${target.name}.`
        : `Referência movida para ${target.name}; evento histórico preservado.`);
      await Promise.all([
        loadPeople(),
        loadReferences(personId, false),
        V5.opened.has(Number(target.id)) ? loadReferences(Number(target.id), false) : Promise.resolve(),
        typeof loadEvents === 'function' ? loadEvents() : Promise.resolve(),
      ]);
    } catch (error) { toast(error.message, 'error'); }
  }

  function chooseCamera() {
    const cameras = (state.cameras || []).filter(camera => camera.enabled);
    if (!cameras.length) return null;
    if (cameras.length === 1) return cameras[0];
    const choices = cameras.map(camera => `${camera.id}: ${camera.name}`).join('\n');
    const raw = prompt(`Escolha o ID da câmera:\n${choices}`, String(cameras[0].id));
    if (raw === null) return null;
    return cameras.find(camera => camera.id === Number(raw)) || null;
  }

  async function captureCamera(personId) {
    const camera = chooseCamera();
    if (!camera) { toast('Escolha uma câmera válida.', 'error'); return; }
    try {
      const scene = await api(`/api/v5/vision/cameras/${camera.id}/live-scene`);
      if (!scene.tracks?.length) { toast('Nenhuma pessoa ativa diante dessa câmera.', 'error'); return; }
      let trackId = scene.tracks[0].track_id;
      if (scene.tracks.length > 1) {
        const lines = scene.tracks.map(track => `#${track.track_id} · ${track.person_name || track.probable_person_name || 'não identificado'}`).join('\n');
        const raw = prompt(`Há mais de uma pessoa. Escolha o track:\n${lines}`, String(trackId));
        if (raw === null) return;
        trackId = Number(raw);
      }
      const kind = prompt('Capturar quais referências? face, body ou both', 'both');
      if (!kind) return;
      const result = await api(`/api/v5/persons/${personId}/enroll/camera/${camera.id}?track_id=${encodeURIComponent(trackId)}&kind=${encodeURIComponent(kind)}`, { method: 'POST', body: '{}' });
      toast(`${result.created.length} referência(s) capturada(s).${result.warnings?.length ? ' ' + result.warnings.join(' ') : ''}`);
      await loadPeople();
    } catch (error) { toast(typeof error.message === 'string' ? error.message : 'Falha ao capturar referências.', 'error'); }
  }

  async function importImage(personId) {
    const input = document.getElementById('v5ImportFile');
    if (!input) return;
    const kind = prompt('A imagem é referência de face, body ou both?', 'face');
    if (!kind) return;
    input.value = '';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const image_base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        const result = await api(`/api/v5/persons/${personId}/enroll/import`, {
          method: 'POST',
          body: JSON.stringify({ image_base64, kind, filename: file.name }),
        });
        toast(`${result.created.length} referência(s) importada(s).`);
        await loadPeople();
      } catch (error) { toast(error.message, 'error'); }
    };
    input.click();
  }

  async function clearReferences(personId) {
    const person = V5.people.find(item => item.id === personId);
    if (!confirm(`Remover todas as referências de ${person?.name || 'esta pessoa'}? O histórico de eventos será preservado.`)) return;
    try {
      const result = await api(`/api/v5/persons/${personId}/references`, { method: 'DELETE' });
      toast(`${result.deleted} referência(s) removida(s).`);
      V5.opened.delete(personId);
      await loadPeople();
    } catch (error) { toast(error.message, 'error'); }
  }

  async function deletePerson(personId) {
    const person = V5.people.find(item => item.id === personId);
    if (!confirm(`Excluir ${person?.name || 'esta pessoa'} e todas as referências? Os eventos serão mantidos, mas voltarão a ficar sem essa identidade.`)) return;
    try {
      await api(`/api/v5/persons/${personId}`, { method: 'DELETE' });
      toast('Pessoa excluída.');
      V5.opened.delete(personId);
      await Promise.all([loadPeople(), typeof loadPersons === 'function' ? loadPersons() : Promise.resolve(), typeof loadEvents === 'function' ? loadEvents() : Promise.resolve()]);
    } catch (error) { toast(error.message, 'error'); }
  }

  function hookIdentityView() {
    if (!ensurePanel()) return false;
    const nav = document.querySelector('[data-view="identity"]');
    nav?.addEventListener('click', () => setTimeout(loadPeople, 0));
    loadPeople();
    return true;
  }

  if (!hookIdentityView()) {
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (hookIdentityView() || tries > 40) clearInterval(timer);
    }, 150);
  }
})();
