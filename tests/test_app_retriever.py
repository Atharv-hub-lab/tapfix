from fastapi.testclient import TestClient

from app.main import create_app


def test_app_builds_bm25_retriever():
    with TestClient(create_app()) as client:
        retriever = client.app.state.retriever

        assert retriever is not None
        assert len(retriever) == 577


def test_health_still_reports_ready():
    with TestClient(create_app()) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_retriever_can_find_catalog_entry():
    with TestClient(create_app()) as client:
        retriever = client.app.state.retriever

        results = retriever.search("Wi-Fi", k=5)

        assert results
        assert all(result.entry_id for result in results)
        assert all(result.uri for result in results)


def test_retriever_does_not_return_dummy_entry():
    with TestClient(create_app()) as client:
        retriever = client.app.state.retriever

        results = retriever.search("settings", k=20)

        assert all(
            result.uri != "bixby://dummy_positive"
            for result in results
        )