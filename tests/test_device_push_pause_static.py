from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DevicePushPauseStaticTests(unittest.TestCase):
    def test_pause_api_is_endpoint_scoped(self) -> None:
        text = (ROOT / "backend" / "app" / "device_push_pause_api.py").read_text(encoding="utf-8")
        self.assertIn("WHERE endpoint = ?", text)
        self.assertIn("SET enabled = ?, updated_at = ? WHERE endpoint = ?", text)
        self.assertNotIn("UPDATE push_subscriptions SET enabled = ?\"", text)

    def test_alert_delivery_still_filters_enabled_subscriptions(self) -> None:
        alerts = (ROOT / "backend" / "app" / "alerts.py").read_text(encoding="utf-8")
        doorbell = (ROOT / "backend" / "app" / "doorbell.py").read_text(encoding="utf-8")
        self.assertIn("push_subscriptions WHERE enabled = 1", alerts)
        self.assertIn("push_subscriptions WHERE enabled = 1", doorbell)

    def test_frontend_never_unsubscribes_browser(self) -> None:
        text = (ROOT / "frontend" / "v57-device-push.js").read_text(encoding="utf-8")
        self.assertIn("/api/push/device/state", text)
        self.assertNotIn("unsubscribe(", text)
        self.assertIn("Pausar neste dispositivo", text)
        self.assertIn("Retomar neste dispositivo", text)


if __name__ == "__main__":
    unittest.main()
