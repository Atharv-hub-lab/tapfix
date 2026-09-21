from app.llm.solution import SolutionDraft
from app.llm.solution_provider import (
    FallbackSolutionProvider,
    SolutionProvider,
)


class FakePrimaryProvider(SolutionProvider):
    def __init__(self):
        self.calls = 0

    def solve(self, query: str, context: str) -> SolutionDraft:
        self.calls += 1
        raise RuntimeError("Gemini quota exceeded")


class FakeFallbackProvider(SolutionProvider):
    def __init__(self):
        self.calls = 0

    def solve(self, query: str, context: str) -> SolutionDraft:
        self.calls += 1

        return SolutionDraft(
            goal="Follow these steps to perform this Device Troubleshooting",
            title="Device troubleshooting",
            score=0.75,
            action_name="Restart Device",
            description="It will guide you through troubleshooting steps.",
            category="manual",
            steps=("Restart the device.",),
            catalog_id=None,
        )


def test_gemini_failure_starts_cooldown():
    primary = FakePrimaryProvider()
    fallback = FakeFallbackProvider()

    provider = FallbackSolutionProvider(
        primary=primary,
        fallback=fallback,
    )

    provider.solve("test query", "test context")
    provider.solve("test query", "test context")

    # Gemini should only be called once.
    assert primary.calls == 1

    # Fallback should handle both requests.
    assert fallback.calls == 2


def test_gemini_cooldown_prevents_repeated_calls():
    primary = FakePrimaryProvider()
    fallback = FakeFallbackProvider()

    provider = FallbackSolutionProvider(
        primary=primary,
        fallback=fallback,
    )

    for _ in range(5):
        provider.solve("test query", "test context")

    # Only the first request should reach Gemini.
    assert primary.calls == 1

    # All five requests should still receive a fallback response.
    assert fallback.calls == 5