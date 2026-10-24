# V7.0 diagnostic findings — session_20261021_144615_b5ba5c05

Observed from the first full diagnostic session on 2026-10-21.

- 240 frontend-observed API calls: all HTTP 200.
- DB invariants: zero orphan recording source events, face samples, body samples, and zero manual identities without person.
- Manual Timeline assignments persisted as `identity_origin=manual` in the final DB summary.
- Vision workers for cameras 2 and 3 remained `running` without PTZ/vision errors.
- Native fault log remained clean after the AMD OpenCL guard.
- Timeline navigation regression root cause: V6.8 and V6.9 were both loaded. V6.8 installs a capture-phase handler for Previous/Next and calls `stopImmediatePropagation()`, preventing the later V6.9 owner from receiving those clicks.
- Tonho overlay could remain over a directly selected visual event because direct visual selection did not always hide the audio overlay.
- Person picker visual regression root cause: `.poi-classify-person-picker { display:grid }` overrode the HTML `hidden` attribute; the picker was visible before `Identificar`, showing the initial empty placeholder without fetching `/api/persons`. The API itself returned 200 when explicitly requested.
- Marker `prompt()` polluted Long Task telemetry: the four extreme 15–70 s long tasks align exactly with the blocking diagnostic marker prompt.
- Screen recording was requested but absent from the ZIP because MediaRecorder data was held only in browser memory and uploaded only on normal stop; page reloads resumed telemetry but discarded the prior screen chunks.
- Diagnostic state looked for `data-v66-session-id`, while the real Tonho track uses `data-audio-id`, so `selected_tonho_id` was always null.
- Snapshot/image loading could not be conclusively diagnosed because V7.0 did not instrument `<img>` load/error/natural dimensions. V7.1 should add this telemetry.
- Recorder log contains many non-monotonic DTS corrections and one corrupt/incomplete prebuffer segment (`moov atom not found`) during concat. This did not surface as an API failure but warrants a separate recorder hardening pass.
