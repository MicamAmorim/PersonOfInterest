from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from .session_diagnostics_api import MAX_SCREEN_BYTES, manager

router = APIRouter(prefix="/api/diagnostics/session", tags=["diagnostics"])


@router.post("/{session_id}/screen-chunk")
async def diagnostic_screen_chunk(
    session_id: str,
    request: Request,
    sequence: int = Query(default=0, ge=0),
) -> dict[str, int | bool]:
    """Persist MediaRecorder chunks incrementally.

    V7.0 uploaded the screen only when MediaRecorder stopped cleanly. A reload
    discarded all chunks held in browser memory. V7.1 stores each chunk while
    the diagnostic is running, so the recording up to a reload/crash survives.
    A new sequence zero truncates any previous partial file for that session.
    """
    folder = manager.ensure_active(session_id)
    body = await request.body()
    if not body:
        return {"ok": True, "bytes": 0, "total_bytes": 0}

    path = folder / "screen.webm"
    existing = path.stat().st_size if path.exists() and sequence > 0 else 0
    if existing + len(body) > MAX_SCREEN_BYTES:
        raise HTTPException(status_code=413, detail="Gravação de tela excede 250 MB")

    mode = "ab" if sequence > 0 and path.exists() else "wb"
    with path.open(mode) as handle:
        handle.write(body)
    return {"ok": True, "bytes": len(body), "total_bytes": int(path.stat().st_size)}
