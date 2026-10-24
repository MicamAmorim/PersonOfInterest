(() => {
  // V7.1 compatibility owner. V6.9 remains available for direct Tonho-track
  // interaction, but this layer owns Prev/Next/±10 deterministically so older
  // document-level handlers cannot race the hybrid player.
  if (document.documentElement.dataset.poiV68V71 === '1') return;
  document.documentElement.dataset.poiV68V71 = '1';

  const S = {
    analysis: null,
    day: null,
    key: '',
    loading: null,
    navToken: 0,
    audioTimer: null,
    diagnosticId: null,
    diagnosticCheckedAt: 0,
    diagnosticCheck: null,
    screenSession: null,
    screenSequence: 0,
  };
  const rawFetch = window.fetch.bind(window);
  const el = id => document.getElementById(id);

  function cameraId() { return Number(el('poiTimelineCamera')?.value || 0) || null; }
  function dateValue() { return el('poiTimelineDate')?.value || ''; }
  function currentSecond() { return Number(el('poiDayScrubber')?.value || 0) || 0; }
  function timelineActive() { return Boolean(el('timelineView')?.classList.contains('active')); }
  function pauseOnEvents() { return Boolean(el('poiV63PauseEvents')?.checked); }
  function hybridPlaying() {
    const play = el('poiHybridPlay');
    const video = el('poiTimelineVideo');
    return Boolean(play?.textContent?.includes('❚') || (video && !video.hidden && !video.paused && !video.ended));
  }

  function pauseHybrid() {
    const play = el('poiHybridPlay');
    if (play?.textContent?.includes('❚')) {
      play.click();
      return;
    }
    const video = el('poiTimelineVideo');
    if (video && !video.hidden && !video.paused) {
      try { video.pause(); } catch (_) {}
    }
  }

  function resumeHybridSoon() {
    setTimeout(() => {
      const play = el('poiHybridPlay');
      if (play && !play.textContent?.includes('❚')) play.click();
    }, 120);
  }

  async function loadData(force = false) {
    const cid = cameraId();
    const date = dateValue();
    if (!cid || !date) return null;
    const key = `${cid}|${date}`;
    if (!force && S.analysis && S.day && S.key === key) return { analysis: S.analysis, day: S.day };
    if (S.loading && S.key === key) return S.loading;
    S.key = key;
    const offset = -new Date().getTimezoneOffset();
    S.loading = Promise.all([
      rawFetch(`/api/timeline-player/analysis?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`, { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(new Error(`analysis ${r.status}`))),
      rawFetch(`/api/timeline-player/day?camera_id=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}&utc_offset_minutes=${encodeURIComponent(offset)}`, { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(new Error(`day ${r.status}`))),
    ]).then(([analysis, day]) => {
      S.analysis = analysis;
      S.day = day;
      return { analysis, day };
    }).catch(() => null).finally(() => { S.loading = null; });
    return S.loading;
  }

  function audioSessions() {
    return Array.isArray(S.analysis?.audio_sessions) ? S.analysis.audio_sessions : [];
  }

  function visualItems() {
    const recordings = (S.day?.recordings || [])
      .filter(rec => rec.file_url && Number(rec.end_second) > Number(rec.start_second))
      .map(rec => ({
        type: 'visual',
        start: Number(rec.start_second || 0),
        end: Number(rec.end_second || 0),
        rec,
        eventId: Number(rec.source_event_id || 0) || null,
      }));
    const events = (S.day?.events || [])
      .filter(event => event.snapshot_url)
      .filter(event => !recordings.some(item => item.start <= Number(event.second || 0) && Number(event.second || 0) <= item.end))
      .map(event => ({
        type: 'visual',
        start: Number(event.second || 0),
        end: Number(event.second || 0),
        event,
        eventId: Number(event.id || 0) || null,
      }));
    return [...recordings, ...events].sort((a, b) => a.start - b.start);
  }

  function temporalItems() {
    const audio = audioSessions().map(session => {
      const start = Number(session.start_second || 0);
      return {
        type: 'audio',
        start,
        end: Math.max(Number(session.end_second || start), start + 4),
        session,
      };
    });
    return [...visualItems(), ...audio].sort((a, b) => {
      const delta = a.start - b.start;
      if (Math.abs(delta) > .001) return delta;
      if (a.type === b.type) return 0;
      return a.type === 'audio' ? -1 : 1;
    });
  }

  function contains(item, second) {
    const t = Number(second) || 0;
    return Number(item.start) - .05 <= t && t <= Number(item.end) + .05;
  }

  function nextTemporal(second) {
    const t = Number(second) || 0;
    return temporalItems().find(item => Number(item.start) > t + .35) || null;
  }

  function previousTemporal(second) {
    const t = Number(second) || 0;
    const items = temporalItems();
    const containing = new Set(items.filter(item => contains(item, t)));
    const candidates = items.filter(item => Number(item.start) < t - .35 && !containing.has(item));
    return candidates.length ? candidates[candidates.length - 1] : null;
  }

  function audioCrossed(fromSecond, toSecond) {
    const from = Number(fromSecond) || 0;
    const to = Number(toSecond) || 0;
    if (to > from) {
      return audioSessions()
        .filter(session => Number(session.start_second || 0) > from + .05 && Number(session.start_second || 0) <= to + .05)
        .sort((a, b) => Number(a.start_second) - Number(b.start_second))[0] || null;
    }
    if (to < from) {
      const matches = audioSessions()
        .filter(session => Number(session.start_second || 0) < from - .05 && Number(session.start_second || 0) >= to - .05)
        .sort((a, b) => Number(a.start_second) - Number(b.start_second));
      return matches.length ? matches[matches.length - 1] : null;
    }
    return null;
  }

  function seekExact(second) {
    const scrubber = el('poiDayScrubber');
    if (!scrubber) return;
    const max = Number(scrubber.max || S.analysis?.day_duration_seconds || 86400);
    scrubber.value = String(Math.max(0, Math.min(max, Math.round(Number(second) || 0))));
    scrubber.dispatchEvent(new Event('input', { bubbles: true }));
    scrubber.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function hideTonhoOverlay() {
    const overlay = el('poiV66AudioOverlay');
    if (overlay) overlay.hidden = true;
    document.querySelectorAll('#poiV66AudioTrack [data-audio-id]').forEach(node => node.classList.remove('selected'));
    if (S.audioTimer) clearTimeout(S.audioTimer);
    S.audioTimer = null;
  }

  function clearVisualSelection() {
    document.querySelectorAll('#poiV63EventTrack [data-event-id],#poiV63ClipTrack [data-event-id],#poiEventMarkers [data-event-id],#poiEventStrip [data-event-card]')
      .forEach(node => node.classList.remove('selected'));
    const eventOverlay = el('poiV63EventOverlay');
    if (eventOverlay) eventOverlay.hidden = true;
    const bbox = el('poiV66BBox');
    if (bbox) bbox.hidden = true;
    const classify = el('poiTimelineClassify');
    if (classify) {
      classify.hidden = true;
      delete classify.dataset.eventId;
    }
  }

  function clock(seconds) {
    const total = Math.max(0, Math.min(86400, Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function esc(value = '') {
    return String(value).replace(/[&<>"']/g, ch => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
  }

  function renderAudio(session) {
    const overlay = el('poiV66AudioOverlay');
    if (!overlay || !session) return;
    document.querySelectorAll('#poiV66AudioTrack [data-audio-id]').forEach(node => {
      node.classList.toggle('selected', Number(node.dataset.audioId) === Number(session.id));
    });
    const time = el('poiV66AudioTime');
    const turns = el('poiV66AudioTurns');
    if (time) time.textContent = clock(session.start_second);
    if (turns) {
      turns.innerHTML = (session.turns || []).map(turn => `
        <div class="poi-v66-audio-turn"><b>Você</b><p>${esc(turn.user || '—')}</p><b class="tonho">Tonho</b><p>${esc(turn.tonho || '—')}</p></div>`
      ).join('') || '<div class="poi-v66-audio-turn"><p>Wake do Tonho detectado.</p></div>';
    }
    overlay.hidden = false;
  }

  function scheduleAudioContinuation(session, wasPlaying) {
    if (!wasPlaying || pauseOnEvents()) return;
    if (S.audioTimer) clearTimeout(S.audioTimer);
    const visibleMs = Math.max(1600, Math.min(6000, Number(session.duration_seconds || 4) * 650));
    S.audioTimer = setTimeout(async () => {
      await loadData(false);
      const next = nextTemporal(Number(session.end_second || session.start_second || 0) + .35);
      if (next) await showTemporalItem(next, true);
    }, visibleMs);
  }

  function focusAudio(session, wasPlaying = false) {
    if (!session) return;
    pauseHybrid();
    clearVisualSelection();
    seekExact(Number(session.start_second || 0));
    renderAudio(session);
    requestAnimationFrame(() => renderAudio(session));
    scheduleAudioContinuation(session, wasPlaying);
  }

  async function showTemporalItem(item, resume = false) {
    if (!item) return;
    if (item.type === 'audio') {
      focusAudio(item.session, resume || hybridPlaying());
      return;
    }
    hideTonhoOverlay();
    clearVisualSelection();
    seekExact(Number(item.start || 0) + (item.rec ? .1 : 0));
    if (resume) resumeHybridSoon();
  }

  async function jumpTemporal(direction) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken) return;
    const second = currentSecond();
    const item = direction > 0 ? nextTemporal(second) : previousTemporal(second);
    if (!item) return;
    await showTemporalItem(item, hybridPlaying());
  }

  async function seekRelativeOwned(delta) {
    const token = ++S.navToken;
    await loadData(false);
    if (token !== S.navToken) return;
    const from = currentSecond();
    const max = Number(el('poiDayScrubber')?.max || S.analysis?.day_duration_seconds || 86400);
    const target = Math.max(0, Math.min(max, from + Number(delta || 0)));
    const wasPlaying = hybridPlaying();
    const crossed = audioCrossed(from, target);
    if (crossed) {
      focusAudio(crossed, wasPlaying);
      return;
    }
    pauseHybrid();
    hideTonhoOverlay();
    clearVisualSelection();
    seekExact(target);
    if (wasPlaying) resumeHybridSoon();
  }

  async function activeDiagnostic(force = false) {
    const now = Date.now();
    if (!force && S.diagnosticCheck) return S.diagnosticCheck;
    if (!force && now - S.diagnosticCheckedAt < 1500) return S.diagnosticId;
    S.diagnosticCheckedAt = now;
    S.diagnosticCheck = rawFetch('/api/diagnostics/session/status', { cache: 'no-store' })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        S.diagnosticId = data?.active?.session_id || null;
        return S.diagnosticId;
      }).catch(() => S.diagnosticId).finally(() => { S.diagnosticCheck = null; });
    return S.diagnosticCheck;
  }

  async function diagnosticEvent(category, kind, data = {}) {
    const id = await activeDiagnostic(false);
    if (!id) return;
    rawFetch(`/api/diagnostics/session/${encodeURIComponent(id)}/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: [{ category, kind, ts: new Date().toISOString(), data }] }),
      keepalive: true,
    }).catch(() => {});
  }

  function navContext(control) {
    return { control, camera_id: cameraId(), date: dateValue(), second: currentSecond() };
  }

  function installNavigationOwner() {
    window.addEventListener('click', event => {
      if (!timelineActive()) return;
      const next = event.target?.closest?.('#poiHybridNext');
      const previous = event.target?.closest?.('#poiHybridPrev');
      const forward = event.target?.closest?.('#poiHybridForward');
      const back = event.target?.closest?.('#poiHybridBack');
      if (!next && !previous && !forward && !back) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (next) {
        void diagnosticEvent('frontend-actions', 'timeline.next_media', navContext('next'));
        void jumpTemporal(1);
      } else if (previous) {
        void diagnosticEvent('frontend-actions', 'timeline.previous_media', navContext('previous'));
        void jumpTemporal(-1);
      } else if (forward) {
        void diagnosticEvent('frontend-actions', 'timeline.seek_forward_10', navContext('forward10'));
        void seekRelativeOwned(10);
      } else if (back) {
        void diagnosticEvent('frontend-actions', 'timeline.seek_back_10', navContext('back10'));
        void seekRelativeOwned(-10);
      }
    }, true);
  }

  function installVisualCleanup() {
    window.addEventListener('click', event => {
      const visual = event.target?.closest?.('#poiV63EventTrack [data-event-id],#poiV63ClipTrack [data-event-id],#poiEventMarkers [data-event-id],#poiEventStrip [data-event-card],#poiCoverageTrack [data-recording-id],#timelineGrid [data-event-card],.timeline-grid [data-event-card]');
      if (visual) hideTonhoOverlay();
    }, true);
  }

  function installPickerHiddenGuard() {
    if (el('poiV68HiddenGuard')) return;
    const style = document.createElement('style');
    style.id = 'poiV68HiddenGuard';
    style.textContent = '.poi-classify-person-picker[hidden]{display:none!important}';
    document.head.appendChild(style);
  }

  function imageInfo(img) {
    if (!(img instanceof HTMLImageElement)) return null;
    let src = '';
    try { src = new URL(img.currentSrc || img.src || '', location.href).pathname; } catch (_) { src = String(img.currentSrc || img.src || '').split('?')[0]; }
    return {
      src: src.slice(0, 300),
      id: img.id || null,
      complete: Boolean(img.complete),
      natural_width: Number(img.naturalWidth || 0),
      natural_height: Number(img.naturalHeight || 0),
      hidden: Boolean(img.hidden),
    };
  }

  function snapshotImageState(reason) {
    const images = Array.from(document.querySelectorAll('#timelineView img,#eventReviewDialog img,#cameraGrid img'))
      .slice(0, 80).map(imageInfo).filter(Boolean);
    void diagnosticEvent('media', 'image.snapshot_state', {
      reason,
      total: images.length,
      loaded: images.filter(item => item.complete && item.natural_width > 0).length,
      failed: images.filter(item => item.complete && item.natural_width === 0).length,
      images,
    });
  }

  function installImageDiagnostics() {
    document.addEventListener('error', event => {
      if (event.target instanceof HTMLImageElement) void diagnosticEvent('media', 'image.error', imageInfo(event.target));
    }, true);
    document.addEventListener('load', event => {
      if (!(event.target instanceof HTMLImageElement)) return;
      const img = event.target;
      if (img.closest?.('#timelineView,#eventReviewDialog,#cameraGrid')) void diagnosticEvent('media', 'image.load', imageInfo(img));
    }, true);
    window.addEventListener('click', event => {
      if (event.target?.closest?.('#poiEventStrip [data-event-card],#timelineGrid [data-event-card],.timeline-grid [data-event-card],#eventReviewDialog')) {
        setTimeout(() => snapshotImageState('after_click'), 220);
      }
    }, true);
  }

  function ensureMarkerDialog() {
    let dialog = el('poiV71MarkerDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'poiV71MarkerDialog';
    dialog.innerHTML = `<form method="dialog" style="min-width:min(520px,calc(100vw - 40px));display:grid;gap:12px;padding:18px;background:#0d141d;color:#eef5ff;border:1px solid #334155;border-radius:14px">
      <strong>⚑ Marcar problema agora</strong>
      <span style="font-size:12px;color:#94a3b8">Descreva brevemente o que você percebeu. Este formulário não bloqueia a thread da interface.</span>
      <textarea id="poiV71MarkerNote" rows="3" maxlength="500" style="resize:vertical;background:#080d13;color:#eef5ff;border:1px solid #334155;border-radius:9px;padding:10px" placeholder="Ex.: Próxima mídia pulou a conversa do Tonho"></textarea>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button value="cancel" class="button ghost">Cancelar</button><button type="button" id="poiV71MarkerSave" class="button primary">Salvar marcador</button></div>
    </form>`;
    document.body.appendChild(dialog);
    el('poiV71MarkerSave')?.addEventListener('click', async () => {
      const note = String(el('poiV71MarkerNote')?.value || '').trim().slice(0, 500);
      const id = await activeDiagnostic(true);
      if (!id) { dialog.close(); return; }
      await rawFetch(`/api/diagnostics/session/${encodeURIComponent(id)}/marker`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }),
      }).catch(() => {});
      await diagnosticEvent('markers', 'user.problem_marker.client', {
        note,
        camera_id: cameraId(), date: dateValue(), second: currentSecond(),
      });
      if (el('poiV71MarkerNote')) el('poiV71MarkerNote').value = '';
      dialog.close();
    });
    return dialog;
  }

  function installNonBlockingMarker() {
    window.addEventListener('click', event => {
      if (!event.target?.closest?.('#poiV70Mark')) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const dialog = ensureMarkerDialog();
      try { dialog.showModal(); } catch (_) { dialog.setAttribute('open', ''); }
      setTimeout(() => el('poiV71MarkerNote')?.focus(), 0);
    }, true);
  }

  function installIncrementalScreenCapture() {
    const Native = window.MediaRecorder;
    if (!Native || window.__poiV71MediaRecorderWrapped) return;
    window.__poiV71MediaRecorderWrapped = true;
    function WrappedMediaRecorder(stream, options) {
      const recorder = new Native(stream, options);
      recorder.addEventListener('dataavailable', event => {
        if (!event.data?.size) return;
        void (async () => {
          const id = await activeDiagnostic(false);
          if (!id) return;
          if (S.screenSession !== id) {
            S.screenSession = id;
            S.screenSequence = 0;
          }
          const seq = S.screenSequence++;
          rawFetch(`/api/diagnostics/session/${encodeURIComponent(id)}/screen-chunk?sequence=${seq}`, {
            method: 'POST', headers: { 'Content-Type': event.data.type || 'video/webm' }, body: event.data,
          }).catch(() => {});
        })();
      });
      return recorder;
    }
    WrappedMediaRecorder.prototype = Native.prototype;
    try { Object.setPrototypeOf(WrappedMediaRecorder, Native); } catch (_) {}
    if (typeof Native.isTypeSupported === 'function') WrappedMediaRecorder.isTypeSupported = Native.isTypeSupported.bind(Native);
    window.MediaRecorder = WrappedMediaRecorder;
  }

  function invalidate() {
    S.analysis = null;
    S.day = null;
    S.key = '';
    S.navToken += 1;
    if (S.audioTimer) clearTimeout(S.audioTimer);
    S.audioTimer = null;
  }

  ['poiTimelineCamera', 'poiTimelineDate'].forEach(id => el(id)?.addEventListener('change', invalidate));
  el('poiTimelineRefresh')?.addEventListener('click', invalidate);
  installPickerHiddenGuard();
  installNavigationOwner();
  installVisualCleanup();
  installImageDiagnostics();
  installNonBlockingMarker();
  installIncrementalScreenCapture();
})();
