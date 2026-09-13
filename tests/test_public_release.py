"""Publication-boundary checks use only synthetic files."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("release_check", Path(__file__).resolve().parents[1] / "scripts/check_public_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize("name", ["data/traces/raw.jsonl", "results/llm_judge/raw.jsonl", ".env", "../outside.txt"])
def test_private_or_escaping_path_cannot_be_allowlisted(tmp_path, name):
    (tmp_path / "release").mkdir()
    (tmp_path / "release/public-files.txt").write_text(name + "\n")
    with pytest.raises(ValueError, match="Private|Unsafe"):
        release.public_files(tmp_path)


def test_symlink_cannot_smuggle_local_records(tmp_path):
    (tmp_path / "release").mkdir()
    (tmp_path / "private.txt").write_text("local evidence")
    (tmp_path / "README.md").symlink_to(tmp_path / "private.txt")
    (tmp_path / "release/public-files.txt").write_text("README.md\n")
    with pytest.raises(ValueError, match="indirect"):
        release.public_files(tmp_path)


def test_unlisted_local_files_are_not_release_inputs(tmp_path):
    (tmp_path / "release").mkdir()
    (tmp_path / "README.md").write_text("public")
    (tmp_path / "local-record.txt").write_text("local evidence")
    (tmp_path / "release/public-files.txt").write_text("README.md\n")
    assert release.public_files(tmp_path) == ["README.md"]
