from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TimelinePlayerStaticTests(unittest.TestCase):
    def test_timeline_api_parses(self) -> None:
        path = ROOT / "backend/app/timeline_player_api.py"
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_day_player_is_additive_to_storage_router(self) -> None:
        api = (ROOT / "backend/app/storage_recording_api.py").read_text(encoding="utf-8")
        self.assertIn("timeline_player_router", api)
        self.assertIn("router.include_router(timeline_player_router)", api)

    def test_player_keeps_legacy_timeline_collapsible(self) -> None:
        js = (ROOT / "frontend/v60-timeline-player.js").read_text(encoding="utf-8")
        self.assertIn("Lista de eventos", js)
        self.assertIn("poi.timeline.legacy.open", js)
        self.assertIn("appendChild(legacy)", js)

    def test_day_player_supports_video_event_snapshot_and_live(self) -> None:
        js = (ROOT / "frontend/v60-timeline-player.js").read_text(encoding="utf-8")
        self.assertIn("poiTimelineVideo", js)
        self.assertIn("poiTimelineSnapshot", js)
        self.assertIn("poiTimelineLive", js)
        self.assertIn("recordingAt", js)
        self.assertIn("eventNear", js)

    def test_mobile_editor_layout_is_present(self) -> None:
        css = (ROOT / "frontend/v60-timeline-player.css").read_text(encoding="utf-8")
        self.assertIn("@media(max-width:760px)", css)
        self.assertIn("width:400%", css)
        self.assertIn("position:sticky", css)
        self.assertIn("scroll-snap-type:x", css)

    def test_assets_are_directly_loaded_and_cached(self) -> None:
        index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        sw = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
        for asset in ("v60-timeline-player.js", "v60-timeline-player.css"):
            self.assertIn(asset, index)
            self.assertIn(asset, sw)
        self.assertIn("personofinterest-v6.0-timeline-player", sw)

    def test_inline_recording_stream_exists_for_browser_seek(self) -> None:
        api = (ROOT / "backend/app/timeline_player_api.py").read_text(encoding="utf-8")
        self.assertIn('/api/timeline-player/recordings/{recording_id}', api)
        self.assertIn('FileResponse(path, media_type="video/mp4")', api)

    def test_event_clips_use_explicit_event_links_not_time_overlap(self) -> None:
        api = (ROOT / "backend/app/timeline_player_api.py").read_text(encoding="utf-8")
        self.assertIn("recording_event_links", api)
        self.assertIn("event_to_recordings", api)
        self.assertIn('rec.get("mode") == "continuous"', api)
        self.assertIn("covered = explicit or source_exact or continuous_cover", api)
        self.assertIn('"event_ids": event_ids', api)


if __name__ == "__main__":
    unittest.main()
