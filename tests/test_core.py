import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        for name in ["app.main", "app.db", "app.config"]:
            sys.modules.pop(name, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rtsp_credentials_are_masked(self):
        from app.main import mask_rtsp_url

        safe, has_credentials = mask_rtsp_url("rtsp://admin:secret@192.168.1.10:554/live?x=1")
        self.assertTrue(has_credentials)
        self.assertNotIn("admin", safe)
        self.assertNotIn("secret", safe)
        self.assertIn("192.168.1.10:554", safe)

    def test_database_initializes(self):
        config = importlib.import_module("app.config")
        db = importlib.import_module("app.db")
        db.init_db()
        self.assertTrue(config.DB_PATH.exists())
        with db.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM cameras").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
