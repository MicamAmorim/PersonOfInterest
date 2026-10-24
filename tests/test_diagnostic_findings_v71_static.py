from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticFindingsV71StaticTests(unittest.TestCase):
    def text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_v68_is_now_single_early_navigation_owner(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn("V7.1 compatibility owner", text)
        self.assertIn("installNavigationOwner", text)
        self.assertIn("event.stopImmediatePropagation()", text)
        self.assertIn("timeline.next_media", text)
        self.assertIn("timeline.previous_media", text)

    def test_relative_seek_cannot_skip_tonho(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn("function audioCrossed", text)
        self.assertIn("const crossed = audioCrossed(from, target)", text)
        self.assertIn("focusAudio(crossed, wasPlaying)", text)

    def test_previous_media_excludes_current_long_recording(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn("const containing = new Set", text)
        self.assertIn("!containing.has(item)", text)

    def test_visual_selection_clears_stale_tonho_overlay(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn("function installVisualCleanup", text)
        self.assertIn("hideTonhoOverlay()", text)
        self.assertIn("#poiV63EventTrack [data-event-id]", text)
        self.assertIn("#poiEventStrip [data-event-card]", text)

    def test_person_picker_respects_hidden_attribute(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn(".poi-classify-person-picker[hidden]{display:none!important}", text)

    def test_diagnostic_marker_is_non_blocking(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn("poiV71MarkerDialog", text)
        self.assertIn("installNonBlockingMarker", text)
        marker_section = text[text.index("function ensureMarkerDialog"):]
        self.assertNotIn("prompt(", marker_section)

    def test_image_failures_are_instrumented(self) -> None:
        text = self.text("frontend/v68-audio-playback-bridge.js")
        self.assertIn("image.error", text)
        self.assertIn("image.load", text)
        self.assertIn("image.snapshot_state", text)
        self.assertIn("natural_width", text)

    def test_screen_chunks_are_persisted_during_recording(self) -> None:
        front = self.text("frontend/v68-audio-playback-bridge.js")
        back = self.text("backend/app/session_diagnostics_v71_patch.py")
        patch = self.text("backend/app/session_diagnostics_patch.py")
        self.assertIn("screen-chunk?sequence=", front)
        self.assertIn('@router.post("/{session_id}/screen-chunk")', back)
        self.assertIn('mode = "ab" if sequence > 0', back)
        self.assertIn("diagnostics_v71_router", patch)

    def test_pwa_cache_bumped(self) -> None:
        sw = self.text("frontend/sw.js")
        self.assertIn("personofinterest-v7.1-diagnostic-findings-fixes", sw)


if __name__ == "__main__":
    unittest.main()
