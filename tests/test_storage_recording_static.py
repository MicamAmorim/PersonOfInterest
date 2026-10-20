from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StorageRecordingStaticTests(unittest.TestCase):
    def test_new_python_modules_parse(self) -> None:
        for relative in (
            "backend/app/false_positive_memory.py",
            "backend/app/false_positive_memory_patch.py",
            "backend/app/storage_recording.py",
            "backend/app/storage_recording_api.py",
            "backend/app/storage_recording_patch.py",
        ):
            path = ROOT / relative
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_destructive_timeline_cleanup_is_off_by_default(self) -> None:
        text = (ROOT / "backend/app/storage_recording.py").read_text(encoding="utf-8")
        self.assertIn("cleanup_enabled INTEGER NOT NULL DEFAULT 0", text)
        self.assertIn("mode TEXT NOT NULL DEFAULT 'off'", text)
        self.assertIn("protect_manual INTEGER NOT NULL DEFAULT 1", text)

    def test_false_positive_memory_survives_event_deletion(self) -> None:
        text = (ROOT / "backend/app/false_positive_memory.py").read_text(encoding="utf-8")
        self.assertIn("ON DELETE SET NULL", text)
        self.assertIn("false_positive_prototypes", text)
        self.assertIn("persistent", text)

    def test_false_positive_timeline_has_separate_mode(self) -> None:
        api_text = (ROOT / "backend/app/storage_recording_api.py").read_text(encoding="utf-8")
        ui_text = (ROOT / "frontend/v58-storage-recording.js").read_text(encoding="utf-8")
        self.assertIn('false_positive_mode: str = Query(default="normal"', api_text)
        self.assertIn("Eventos normais", ui_text)
        self.assertIn("Falsos positivos", ui_text)
        self.assertIn("/api/storage/events", ui_text)

    def test_recorder_isolated_from_tracker(self) -> None:
        text = (ROOT / "backend/app/storage_recording.py").read_text(encoding="utf-8")
        self.assertIn("go2rtc.local_restream_url", text)
        self.assertNotIn("vision_manager", text)
        self.assertNotIn("PersistentTrack", text)

    def test_frontend_assets_are_loaded_directly(self) -> None:
        index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        sw = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
        for asset in ("v58-storage-recording.js", "v58-storage-recording.css"):
            self.assertIn(asset, index)
            self.assertIn(asset, sw)

    def test_compiled_build_collects_ffmpeg_runtime(self) -> None:
        spec = (ROOT / "packaging/PersonOfInterest.spec").read_text(encoding="utf-8")
        requirements = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
        self.assertIn('"imageio_ffmpeg"', spec)
        self.assertIn("imageio-ffmpeg", requirements)


if __name__ == "__main__":
    unittest.main()
