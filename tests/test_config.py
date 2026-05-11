import os

from searchapi_eval.config import load_env_file


def test_load_env_file_preserves_existing_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text('SEARCHAPI_TEST_VALUE="from_file"\n', encoding="utf-8")
    monkeypatch.setenv("SEARCHAPI_TEST_VALUE", "from_env")

    load_env_file(env_path)

    assert os.environ["SEARCHAPI_TEST_VALUE"] == "from_env"


def test_load_env_file_sets_missing_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("SEARCHAPI_TEST_MISSING=from_file\n", encoding="utf-8")
    monkeypatch.delenv("SEARCHAPI_TEST_MISSING", raising=False)

    load_env_file(env_path)

    assert os.environ["SEARCHAPI_TEST_MISSING"] == "from_file"

