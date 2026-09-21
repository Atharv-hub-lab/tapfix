import json

import pytest
from fastapi.testclient import TestClient

from app.catalog import CatalogIndex
from app.config import PROJECT_ROOT, Settings
from app.main import create_app

DATA_DIR = PROJECT_ROOT / "data"
NEEDED_FILES = ["deeplinks.json", "siis_responses.json", "input.txt", "sample_output.json"]


def _missing_files():
    return [name for name in NEEDED_FILES if not (DATA_DIR / name).exists()]


def pytest_report_header(config):
    missing = _missing_files()
    if missing:
        return f"TapFix: Samsung data MISSING in data/: {missing} (data-dependent tests will be skipped)"
    return "TapFix: Samsung data found in data/ (all tests will run)"


@pytest.fixture(scope="session")
def settings():
    missing = _missing_files()
    if missing:
        pytest.skip(f"Copy Samsung's files into data/ first. Missing: {missing}")
    return Settings(data_dir=DATA_DIR)


@pytest.fixture(scope="session")
def catalog(settings):
    return CatalogIndex.from_file(settings.deeplinks_path)


@pytest.fixture(scope="session")
def sample_output(settings):
    return json.loads(settings.sample_output_path.read_text(encoding="utf-8-sig"))


@pytest.fixture()
def client(settings):
    # `with` runs the app's startup, which loads the data.
    with TestClient(create_app(settings)) as test_client:
        yield test_client
