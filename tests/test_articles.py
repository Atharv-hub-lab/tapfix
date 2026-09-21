import json

import pytest

from app.api_models import SiisArticle
from app.articles import ArticleError, load_queries, load_siis_records, siis_text


def test_real_siis_records_load(settings):
    records = load_siis_records(settings.siis_path)
    assert len(records) == 20
    assert len({r.id for r in records}) == 20
    assert all(r.title and r.content.strip() and r.original_query for r in records)


def test_real_queries_load(settings):
    queries = load_queries(settings.input_path)
    assert len(queries) == 20
    assert all(q.strip() for q in queries)


def test_siis_text_accepts_string_dict_and_model():
    assert siis_text("plain text") == ("", "plain text")
    assert siis_text({"title": "T", "content": "C"}) == ("T", "C")
    assert siis_text(SiisArticle(title="T", content="C")) == ("T", "C")


def test_siis_text_rejects_non_string_fields():
    with pytest.raises(ArticleError):
        siis_text({"title": "T", "content": 123})


def test_missing_siis_file_gives_clear_error(tmp_path):
    with pytest.raises(ArticleError, match="not found"):
        load_siis_records(tmp_path / "nope.json")


def test_siis_record_with_empty_content_is_rejected(tmp_path):
    path = tmp_path / "siis.json"
    payload = {"responses": [{"id": "r1", "original_query": "q", "siis_response": {"title": "t", "content": "  "}}]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArticleError, match="empty content"):
        load_siis_records(path)


def test_duplicate_siis_ids_are_rejected(tmp_path):
    path = tmp_path / "siis.json"
    rec = {"id": "r1", "original_query": "q", "siis_response": {"title": "t", "content": "c"}}
    path.write_text(json.dumps({"responses": [rec, rec]}), encoding="utf-8")
    with pytest.raises(ArticleError, match="duplicate"):
        load_siis_records(path)
