from app.cache import FastPathCache
from app.catalog import CatalogIndex
from app.llm.provider import LLMProvider
from app.llm.solution import SolutionDraft
from app.llm.solution_gemini import GeminiSolutionProvider
from app.llm.solution_provider import DeterministicSolutionProvider
from app.nlp.query import QueryIntent
from app.troubleshoot_service import TroubleshootService


class FakeQueryProvider(LLMProvider):
    def understand(self, query: str) -> QueryIntent:
        return QueryIntent(
            original_query=query,
            normalized_query="wifi connection",
            direction="ON",
            keywords=("wifi", "wireless"),
        )


class FakeSolutionProvider(GeminiSolutionProvider):
    def __init__(self):
        pass

    def solve(self, query: str, context: str) -> SolutionDraft:
        return SolutionDraft(
            goal="Follow these steps to perform this Wi-Fi Troubleshooting",
            title="Wi-Fi settings",
            score=0.95,
            action_name="Enable Wi-Fi",
            description="It will open Wi-Fi settings for you.",
            category="auto",
            steps=("Open Wi-Fi settings.",),
            catalog_id="DL-TEST",
        )


class FakeEntry:
    def __init__(self):
        self.id = "DL-TEST"
        self.label = "Wi-Fi"
        self.description = "Wi-Fi settings"
        self.category = "connectivity"


class FakeCandidate:
    def __init__(self):
        self.entry_id = "DL-TEST"
        self.uri = "bixby://settings/wifi"
        self.entry = FakeEntry()
        self.score = 0.95
        self.rank = 1
        self.matched_terms = ("wifi",)


class FakeRetriever:
    def search(self, query: str, k: int = 10):
        return [FakeCandidate()]


class EmptyRetriever:
    def search(self, query: str, k: int = 10):
        return []


def make_catalog(tmp_path):
    catalog_file = tmp_path / "deeplinks.json"

    catalog_file.write_text(
        """
        {
          "deeplinks": [
            {
              "id": "DL-TEST",
              "label": "Wi-Fi",
              "description": "Wi-Fi settings",
              "category": "connectivity",
              "deeplink": "bixby://settings/wifi"
            },
            {
              "id": "DL-DUMMY",
              "label": "Dummy",
              "description": "Dummy positive test entry",
              "category": "test",
              "deeplink": "bixby://dummy_positive"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    return CatalogIndex.from_file(catalog_file)


def test_complete_troubleshooting_pipeline(tmp_path):
    service = TroubleshootService(
        retriever=FakeRetriever(),
        catalog=make_catalog(tmp_path),
        query_provider=FakeQueryProvider(),
        solution_provider=FakeSolutionProvider(),
    )

    result = service.troubleshoot(
        "My Wi-Fi will not turn on",
    )

    assert result.ok is True

    context = result.response["contexts"][0]

    assert context["title"] == "Wi-Fi settings"
    assert context["actions"][0]["actionName"] == "Enable Wi-Fi"


def test_cache_exact_query_hit(tmp_path):
    cache = FastPathCache()

    service = TroubleshootService(
        retriever=FakeRetriever(),
        catalog=make_catalog(tmp_path),
        query_provider=FakeQueryProvider(),
        solution_provider=FakeSolutionProvider(),
        cache=cache,
    )

    first_result = service.troubleshoot(
        "My Wi-Fi will not turn on",
    )

    second_result = service.troubleshoot(
        "My Wi-Fi will not turn on",
    )

    assert first_result.ok is True
    assert second_result.ok is True

    stats = cache.stats()

    assert stats["exact_hits"] == 1
    assert stats["hits"] == 1


def test_cache_paraphrase_hit(tmp_path):
    cache = FastPathCache()

    service = TroubleshootService(
        retriever=FakeRetriever(),
        catalog=make_catalog(tmp_path),
        query_provider=FakeQueryProvider(),
        solution_provider=FakeSolutionProvider(),
        cache=cache,
    )

    first_result = service.troubleshoot(
        "My Wi-Fi will not turn on",
    )

    second_result = service.troubleshoot(
        "Please switch my Wi-Fi on",
    )

    assert first_result.ok is True
    assert second_result.ok is True

    stats = cache.stats()

    assert stats["paraphrase_hits"] == 1
    assert stats["hits"] == 1


def test_cache_matches_display_black_paraphrase(tmp_path):
    cache = FastPathCache()

    service = TroubleshootService(
        retriever=EmptyRetriever(),
        catalog=make_catalog(tmp_path),
        query_provider=FakeQueryProvider(),
        solution_provider=FakeSolutionProvider(),
        cache=cache,
    )

    first_result = service.troubleshoot(
        "My phone display is completely black",
    )

    second_result = service.troubleshoot(
        "The display on my phone has gone black",
    )

    assert first_result.ok is True
    assert second_result.ok is True

    stats = cache.stats()

    assert stats["paraphrase_hits"] == 1
    assert stats["hits"] == 1


def test_cache_separates_different_siis_contexts(tmp_path):
    cache = FastPathCache()

    service = TroubleshootService(
        retriever=FakeRetriever(),
        catalog=make_catalog(tmp_path),
        query_provider=FakeQueryProvider(),
        solution_provider=FakeSolutionProvider(),
        cache=cache,
    )

    siis_a = {
        "title": "Wi-Fi troubleshooting",
        "content": "Check the Wi-Fi settings.",
    }

    siis_b = {
        "title": "Bluetooth troubleshooting",
        "content": "Check the Bluetooth settings.",
    }

    first_result = service.troubleshoot(
        "My Wi-Fi will not turn on",
        siis_response=siis_a,
    )

    second_result = service.troubleshoot(
        "My Wi-Fi will not turn on",
        siis_response=siis_b,
    )

    assert first_result.ok is True
    assert second_result.ok is True

    stats = cache.stats()

    assert stats["exact_hits"] == 0


def test_unseen_siis_scenario_uses_manual_fallback(tmp_path):
    cache = FastPathCache()

    service = TroubleshootService(
        retriever=EmptyRetriever(),
        catalog=make_catalog(tmp_path),
        query_provider=FakeQueryProvider(),
        solution_provider=DeterministicSolutionProvider(),
        cache=cache,
    )

    siis_response = {
        "title": "Unknown device issue",
        "content": (
            "Check the device and follow the available troubleshooting guidance."
        ),
    }

    result = service.troubleshoot(
        "My phone has a strange problem I cannot identify",
        siis_response=siis_response,
    )

    assert result.ok is True
    assert result.response["contexts"]

    context = result.response["contexts"][0]

    assert context["actions"]

    action = context["actions"][0]

    assert action["category"] == "manual"
    assert action["stepGroups"]

    steps = action["stepGroups"][0]["steps"]

    assert steps
    assert "Check the device" in steps[0]