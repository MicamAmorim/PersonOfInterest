from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_start_disables_opencv_opencl_before_cv2_checks() -> None:
    script = (ROOT / "start.ps1").read_text(encoding="utf-8")
    guard = '$env:OPENCV_OPENCL_RUNTIME = "disabled"'
    first_cv2 = 'import cv2'
    assert guard in script
    assert first_cv2 in script
    assert script.index(guard) < script.index(first_cv2)


def test_opencl_guard_is_opt_out_not_hardcoded_forever() -> None:
    script = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert 'POI_DISABLE_OPENCL' in script
    assert '@("0", "false", "no", "off")' in script


def test_env_example_documents_default_guard() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "POI_DISABLE_OPENCL=1" in env
