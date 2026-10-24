from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UXRefinementStaticTests(unittest.TestCase):
    def test_false_positive_api_is_bounded(self) -> None:
        path = ROOT / "backend/app/storage_recording_api.py"
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        text = path.read_text(encoding="utf-8")
        self.assertIn('limit: int = Query(default=30, ge=1, le=500)', text)
        self.assertIn('LIMIT ? OFFSET ?', text)

    def test_legacy_timeline_defaults_to_30(self) -> None:
        text = (ROOT / "frontend/v58-storage-recording.js").read_text(encoding="utf-8")
        self.assertIn("poi.timeline.legacy.limit", text)
        self.assertIn("timelineResultLimit", text)
        self.assertIn("V58.timelineLimit", text)
        self.assertNotIn("params.set('limit', '500')", text)

    def test_recording_cards_have_compact_actions(self) -> None:
        text = (ROOT / "frontend/v58-storage-recording.js").read_text(encoding="utf-8")
        self.assertIn("data-rec-edit", text)
        self.assertIn("data-rec-disable", text)
        self.assertIn("Configurada · aguardando próximo evento", text)
        self.assertIn("data-rec-event-field", text)
        self.assertIn("data-rec-segment-field", text)

    def test_false_positive_management_is_collapsible_and_limited(self) -> None:
        text = (ROOT / "frontend/v58-storage-recording.js").read_text(encoding="utf-8")
        self.assertIn("v58FpDetails", text)
        self.assertIn("v58FpLimit", text)
        self.assertIn("/api/false-positives/prototypes?limit=", text)

    def test_new_timeline_syncs_marker_to_thumbnail(self) -> None:
        text = (ROOT / "frontend/v61-timeline-interactions.js").read_text(encoding="utf-8")
        self.assertIn("scrollCardToCenter", text)
        self.assertIn("poi-event-marker.selected", (ROOT / "frontend/v61-timeline-interactions.css").read_text(encoding="utf-8"))
        self.assertIn("syncSelection", text)

    def test_timeline_classification_reuses_existing_routes(self) -> None:
        text = (ROOT / "frontend/v61-timeline-interactions.js").read_text(encoding="utf-8")
        self.assertIn("/api/identity/events/${id}/assign", text)
        self.assertIn("/api/events/${id}/false-positive?value=", text)
        self.assertIn("poiTimelineClassify", text)

    def test_v61_assets_are_direct_and_cached(self) -> None:
        index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        sw = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
        for asset in ("v61-timeline-interactions.js", "v61-timeline-interactions.css"):
            self.assertIn(asset, index)
            self.assertIn(asset, sw)


if __name__ == "__main__":
    unittest.main()
