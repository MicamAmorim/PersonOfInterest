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
        self.assertIn("Automatic matches never update the centroid", text)

    def test_persistent_negative_support_is_bounded(self) -> None:
        text = (ROOT / "backend/app/false_positive_memory_patch.py").read_text(encoding="utf-8")
        self.assertIn("support_count", text)
        self.assertIn("min(3, support.get(prototype_id, 1))", text)

    def test_unlearn_removes_legacy_matcher_samples(self) -> None:
        text = (ROOT / "backend/app/storage_recording_api.py").read_text(encoding="utf-8")
        self.assertIn("DELETE FROM body_negative_samples", text)
        self.assertIn("legacy_negative_samples_removed", text)
        self.assertIn("deactivate_prototype", text)

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

    def test_recorder_patch_keeps_video_copy_and_aac_audio(self) -> None:
        text = (ROOT / "backend/app/storage_recording_patch.py").read_text(encoding="utf-8")
        self.assertIn('"-c:v",\n                "copy"', text)
        self.assertIn('"-c:a",\n                "aac"', text)

    def test_database_compaction_is_explicit_only(self) -> None:
        api_text = (ROOT / "backend/app/storage_recording_api.py").read_text(encoding="utf-8")
        ui_text = (ROOT / "frontend/v59-db-maintenance.js").read_text(encoding="utf-8")
        self.assertIn('@router.post("/api/storage/compact")', api_text)
        self.assertIn('conn.execute("VACUUM")', api_text)
        self.assertIn("Compactar banco", ui_text)
        storage_text = (ROOT / "backend/app/storage_recording.py").read_text(encoding="utf-8")
        self.assertNotIn('execute("VACUUM")', storage_text)

    def test_frontend_assets_are_loaded_directly(self) -> None:
        index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        sw = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
        for asset in (
            "v58-storage-recording.js",
            "v58-storage-recording.css",
            "v59-db-maintenance.js",
        ):
            self.assertIn(asset, index)
            self.assertIn(asset, sw)

    def test_compiled_build_collects_ffmpeg_runtime(self) -> None:
        spec = (ROOT / "packaging/PersonOfInterest.spec").read_text(encoding="utf-8")
        requirements = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
        start = (ROOT / "start.ps1").read_text(encoding="utf-8")
        self.assertIn('"imageio_ffmpeg"', spec)
        self.assertIn("imageio-ffmpeg", requirements)
        self.assertIn("imageio_ffmpeg", start)


if __name__ == "__main__":
    unittest.main()
