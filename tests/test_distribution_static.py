from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DistributionStaticTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        path = ROOT / relative
        self.assertTrue(path.is_file(), f"arquivo obrigatório ausente: {relative}")
        return path.read_text(encoding="utf-8")

    def test_windows_setup_offers_optional_autostart(self) -> None:
        setup = self.read("setup.ps1")
        self.assertIn("ServerAutostart", setup)
        self.assertIn("install-server-autostart.ps1", setup)
        self.assertIn("start.ps1", setup)

    def test_autostart_reuses_normal_server_start(self) -> None:
        installer = self.read("install-server-autostart.ps1")
        runner = self.read("server-autostart-runner.ps1")
        remover = self.read("remove-server-autostart.ps1")
        self.assertIn("PersonOfInterest Server", installer)
        self.assertIn("server-autostart-runner.ps1", installer)
        self.assertIn("start.ps1", runner)
        self.assertIn("-NoBrowser", runner)
        self.assertIn("/api/health", runner)
        self.assertIn("Unregister-ScheduledTask", remover)

    def test_packaged_launcher_is_valid_python(self) -> None:
        launcher = self.read("packaging/launcher.py")
        ast.parse(launcher)
        self.assertIn('os.environ["DATA_DIR"]', launcher)
        self.assertIn('from app.main import app', launcher)
        self.assertLess(
            launcher.index('os.environ["DATA_DIR"]'),
            launcher.index('from app.main import app'),
            "DATA_DIR precisa ser configurado antes de importar app.main",
        )
        self.assertIn("/api/streams", launcher)

    def test_pyinstaller_spec_bundles_runtime_assets(self) -> None:
        spec = self.read("packaging/PersonOfInterest.spec")
        self.assertIn('"frontend"', spec)
        self.assertIn('"go2rtc.exe"', spec)
        self.assertIn('"go2rtc"', spec)
        self.assertIn("POI_BUNDLE_MODELS", spec)
        self.assertIn("COLLECT", spec)

    def test_platform_build_scripts_exist(self) -> None:
        windows = self.read("build-windows.ps1")
        linux = self.read("build-linux.sh")
        self.assertIn("PersonOfInterest.spec", windows)
        self.assertIn("PersonOfInterest.spec", linux)
        self.assertIn("BundleModels", windows)
        self.assertIn("--bundle-models", linux)


if __name__ == "__main__":
    unittest.main()
