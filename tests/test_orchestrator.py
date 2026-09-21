from app.llm.orchestrator import build_solution_context
from app.llm.provider import LLMProvider
from app.llm.solution import SolutionDraft
from app.llm.solution_provider import SolutionProvider
from app.nlp.query import QueryIntent


class FakeQueryProvider(LLMProvider):
    def understand(self, query: str) -> QueryIntent:
        return QueryIntent(
            original_query=query,
            normalized_query="wifi connection",
            direction="ON",
            keywords=("wifi", "wireless"),
        )


class FakeSolutionProvider(SolutionProvider):
    def solve(self, query: str, context: str) -> SolutionDraft:
        assert query == "My Wi-Fi will not turn on"
        assert "Candidate 1:" in context
        assert "DL-TEST" in context
        assert "Wi-Fi" in context

        return SolutionDraft(
            goal="Turn on Wi-Fi",
            title="Wi-Fi",
            score=0.95,
            action_name="Enable Wi-Fi",
            description="Enable Wi-Fi from Settings.",
            category="auto",
            steps=("Open Wi-Fi settings.",),
            catalog_id="DL-TEST",
        )
class FakeEntry:
    def __init__(self):
        self.id = "DL-TEST"
        self.label = "Wi-Fi"
        self.description = "Wi-Fi settings"
        self.message = "Wi-Fi settings"
        self.qna_description = "Wi-Fi connection settings"
        self.category = "connectivity"

class FakeCatalog:
    def get_by_id(self, entry_id):
        if entry_id == "DL-TEST":
            return FakeEntry()
        return None


class FakeCandidate:
    def __init__(self):
        self.entry_id = "DL-TEST"
        self.uri = "bixby://settings/wifi"
        self.score = 0.95
        self.rank = 1
        self.matched_terms = ("wifi",)


class FakeRetriever:
    def search(self, query: str, k: int = 10):
        assert query == "wifi connection"

        return [
            FakeCandidate(),
        ]


def test_build_solution_context_runs_stage_one_retrieval_and_stage_two():
    result = build_solution_context(
        query="My Wi-Fi will not turn on",
        retriever=FakeRetriever(),
        catalog=FakeCatalog(),
        query_provider=FakeQueryProvider(),
        solution_provider=FakeSolutionProvider(),
    )

    assert result.query.intent.normalized_query == "wifi connection"
    assert len(result.candidates) == 1
    assert result.candidates[0].entry_id == "DL-TEST"

    assert result.solution.goal == "Turn on Wi-Fi"
    assert result.solution.catalog_id == "DL-TEST"
class SIISRetriever:
    def search(self, query: str, k: int = 10):
        if query == "wifi connection":
            return [
                FakeCandidate(),
            ]

        if "blank or black display" in query.lower():
            return [
                FakeCandidate(),
            ]

        return []


class SIISFakeSolutionProvider(SolutionProvider):
    def solve(self, query: str, context: str) -> SolutionDraft:
        assert "SIIS TROUBLESHOOTING EVIDENCE:" in context
        assert "title=Blank or black display" in context
        assert "content=If your phone or tablet screen is blank or black" in context
        assert "CATALOG CANDIDATES:" in context
        assert "DL-TEST" in context

        return SolutionDraft(
            goal="Follow these steps to perform this Device Troubleshooting",
            title="Device troubleshooting",
            score=0.75,
            action_name="Restart Device",
            description="It will guide you through troubleshooting steps.",
            category="manual",
            steps=(
                "Check for physical or liquid damage.",
                "Force restart the device.",
            ),
            catalog_id=None,
        )


def test_build_solution_context_includes_siis_evidence_and_retrieval():
    result = build_solution_context(
        query="My phone screen is completely black",
        retriever=SIISRetriever(),
        catalog=FakeCatalog(),
        query_provider=FakeQueryProvider(),
        solution_provider=SIISFakeSolutionProvider(),
        siis_response={
            "title": "Blank or black display on a Samsung phone or tablet",
            "content": (
                "If your phone or tablet screen is blank or black, "
                "check for physical or liquid damage."
            ),
        },
    )

    assert result.solution.category == "manual"
    assert result.solution.catalog_id is None
    assert len(result.candidates) >= 1