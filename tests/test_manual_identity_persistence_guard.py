from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manual_identity_persistence_guard_is_installed_late() -> None:
    patch = (ROOT / "backend" / "app" / "timeline_analysis_patch.py").read_text(encoding="utf-8")
    assert "manual_identity_persistence_patch" in patch
    assert "install_manual_identity_persistence()" in patch


def test_late_face_result_cannot_override_manual_identity() -> None:
    patch = (ROOT / "backend" / "app" / "manual_identity_persistence_patch.py").read_text(encoding="utf-8")
    assert "identity_origin" in patch
    assert "manual_person_id" in patch
    assert '"person_id": manual_person_id' in patch
    assert '"cluster_id": None' in patch
    assert '"identity_state": "known"' in patch
    assert '"identity_confidence": 1.0' in patch
    assert "assistant_eligible = 0" in patch
    assert "UPDATE face_samples SET person_id = ?, cluster_id = NULL" in patch


def test_late_unknown_cluster_is_repaired_after_manual_review() -> None:
    patch = (ROOT / "backend" / "app" / "manual_identity_persistence_patch.py").read_text(encoding="utf-8")
    assert "_repair_cluster" in patch
    assert "DELETE FROM unknown_clusters" in patch
    assert "UPDATE unknown_clusters" in patch
