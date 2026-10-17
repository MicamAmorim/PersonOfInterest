import unittest
from unittest.mock import patch

from backend.app import discovery


class DiscoveryTests(unittest.TestCase):
    def test_digest_challenge_parser(self):
        parsed = discovery._parse_digest_challenge('Digest realm="cam", nonce="abc", qop="auth"')
        self.assertEqual(parsed["realm"], "cam")
        self.assertEqual(parsed["nonce"], "abc")
        self.assertEqual(parsed["qop"], "auth")

    def test_digest_authorization_contains_required_fields(self):
        header = discovery._digest_authorization(
            "user", "pass", "DESCRIBE", "rtsp://192.168.1.10:554/live/ch00_0",
            'Digest realm="cam", nonce="abc", qop="auth"',
        )
        self.assertTrue(header.startswith("Digest "))
        self.assertIn('username="user"', header)
        self.assertIn('realm="cam"', header)
        self.assertIn('nonce="abc"', header)
        self.assertIn("response=", header)

    @patch("backend.app.discovery.get_local_ipv4", return_value="192.168.1.11")
    def test_local_target_guard(self, _):
        self.assertEqual(str(discovery.ensure_local_target("192.168.1.151")), "192.168.1.151")
        with self.assertRaises(ValueError):
            discovery.ensure_local_target("192.168.2.10")

    def test_extract_existing_hosts(self):
        hosts = discovery.hosts_from_rtsp_urls([
            "rtsp://user:pass@192.168.1.151:554/live/ch00_0",
            "rtsp://192.168.1.10:554/live/ch00_0",
        ])
        self.assertEqual(hosts, {"192.168.1.151", "192.168.1.10"})


if __name__ == "__main__":
    unittest.main()
