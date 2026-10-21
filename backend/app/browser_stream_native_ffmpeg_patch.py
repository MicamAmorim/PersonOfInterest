from __future__ import annotations


def install() -> None:
    """Replace the earlier exec-based browser stream source with go2rtc's native
    FFmpeg source syntax.

    go2rtc supports using another go2rtc stream name as an FFmpeg input, e.g.
    ``ffmpeg:camera1#video=h264#audio=opus``.  This avoids Windows command-line
    quoting issues around the imageio-ffmpeg executable while keeping the
    browser transcoder lazy: FFmpeg starts only when the derived stream is
    consumed.
    """
    from . import go2rtc

    if getattr(go2rtc, "_poi_browser_stream_native_ffmpeg_patch", False):
        return

    # browser_stream_patch already exposes the deterministic naming helper.
    browser_name = getattr(go2rtc, "browser_stream_name", lambda name: f"{name}_browser")

    # browser_stream_patch wrapped the original function.  Its wrapper would try
    # to create the old exec:-based stream after every primary upsert, so unwrap
    # one layer by capturing the pre-wrapper function stored in its closure when
    # available.  If that implementation detail ever changes, fall back to the
    # currently installed function and explicitly overwrite the derived stream
    # afterwards.
    installed_upsert = go2rtc.upsert_stream
    installed_delete = go2rtc.delete_stream

    original_upsert = None
    closure = getattr(installed_upsert, "__closure__", None) or ()
    freevars = getattr(installed_upsert, "__code__", None)
    freevar_names = tuple(getattr(freevars, "co_freevars", ()) or ())
    for name, cell in zip(freevar_names, closure):
        if name == "original_upsert":
            try:
                original_upsert = cell.cell_contents
            except Exception:
                pass
            break
    if original_upsert is None:
        original_upsert = installed_upsert

    original_delete = None
    closure = getattr(installed_delete, "__closure__", None) or ()
    freevars = getattr(installed_delete, "__code__", None)
    freevar_names = tuple(getattr(freevars, "co_freevars", ()) or ())
    for name, cell in zip(freevar_names, closure):
        if name == "original_delete":
            try:
                original_delete = cell.cell_contents
            except Exception:
                pass
            break
    if original_delete is None:
        original_delete = installed_delete

    def upsert_stream(stream_name: str, rtsp_url: str, extra_sources=None):
        result = original_upsert(stream_name, rtsp_url, extra_sources)
        if not result.ok or stream_name.endswith(("_talkback", "_browser")):
            return result

        derived = browser_name(stream_name)
        native_source = f"ffmpeg:{stream_name}#video=h264#audio=opus"
        browser_result = original_upsert(derived, native_source)
        if not browser_result.ok:
            result.warning = f"Stream H.264 do navegador indisponível: {browser_result.error}"
        return result

    def delete_stream(stream_name: str):
        if not stream_name.endswith(("_talkback", "_browser")):
            try:
                original_delete(browser_name(stream_name))
            except Exception:
                pass
        return original_delete(stream_name)

    go2rtc.upsert_stream = upsert_stream
    go2rtc.delete_stream = delete_stream
    go2rtc._poi_browser_stream_native_ffmpeg_patch = True  # type: ignore[attr-defined]
