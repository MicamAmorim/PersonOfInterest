from __future__ import annotations


def install() -> None:
    """Marker module documenting the V7.2.1 browser-cache compatibility fix.

    Actual URL versioning lives in timeline_player_api and response cache headers
    live in browser_media_route_patch. Keeping this module tiny makes the change
    explicit without adding another runtime monkey-patch layer.
    """
    return None
