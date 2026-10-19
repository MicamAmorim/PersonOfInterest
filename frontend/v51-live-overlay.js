(() => {
  function install() {
    if (typeof renderVisionOverlay !== 'function' || window.__poiV51Overlay) return false;

    renderVisionOverlay = function renderPersistentVisionOverlay(vision) {
      const overlay = $('#visionOverlay');
      if (!overlay) return;
      const tracks = vision.tracks || [];
      overlay.innerHTML = tracks.map(track => {
        const b = track.bbox;
        const selected = Number(track.track_id) === Number(state.viewer.selectedTrackId);
        const stable = track.control_valid !== false;
        const cls = `${selected ? 'selected' : ''} ${track.has_face ? 'face' : ''} ${stable ? '' : 'unstable'} ${track.face_search ? 'face-search' : ''}`;
        let identity = '';
        if (track.person_name) identity = ` · ${escapeHtml(track.person_name)}`;
        else if (track.probable_person_name) identity = ` · Provável: ${escapeHtml(track.probable_person_name)}`;
        else if (track.identity_state === 'collecting') identity = ' · coletando';
        else if (track.identity_state === 'unknown') identity = ' · desconhecido';
        let suffix = stable ? '' : ' · aguardando';
        if (track.face_search) suffix += ' · procurando rosto';
        const observations = Number(track.observation_count || 0);
        const title = [
          track.control_reason || '',
          track.identity_state ? `identidade: ${track.identity_state}` : '',
          observations ? `${observations} observações` : '',
        ].filter(Boolean).join(' · ');
        return `<button class="track-box ${cls}" title="${escapeHtml(title)}" data-track-id="${track.track_id}" style="left:${b.x * 100}%;top:${b.y * 100}%;width:${b.w * 100}%;height:${b.h * 100}%"><span>#${track.track_id}${identity}${track.has_face ? ' · face' : ''}${suffix}</span></button>`;
      }).join('');
      $$('[data-track-id]').forEach(el => el.addEventListener('click', async event => {
        event.stopPropagation();
        state.viewer.selectedTrackId = Number(el.dataset.trackId);
        $('#trackHint').textContent = `Pessoa #${state.viewer.selectedTrackId} selecionada.`;
        if ($('#autoFollowToggle').checked) await setAutoFollow(true);
        renderVisionOverlay(vision);
      }));
    };

    window.__poiV51Overlay = true;
    return true;
  }

  if (!install()) {
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (install() || tries > 40) clearInterval(timer);
    }, 150);
  }
})();
