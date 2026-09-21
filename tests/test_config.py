from pathlib import Path

from app.config import Settings


def test_api_key_is_never_printed_or_logged():
    settings = Settings(llm_api_key="super-secret-key-123")
    assert "super-secret-key-123" not in repr(settings)
    assert "super-secret-key-123" not in str(settings.safe_dict())
    assert settings.safe_dict()["llm_api_key"] == "***set***"


def test_unset_key_is_reported_as_not_set():
    assert Settings().safe_dict()["llm_api_key"] == "(not set)"


def test_data_dir_can_be_overridden_by_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("TAPFIX_DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.data_dir == Path(tmp_path)
    assert settings.deeplinks_path == Path(tmp_path) / "deeplinks.json"
