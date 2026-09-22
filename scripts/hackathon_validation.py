from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

import httpx

from app.catalog import CatalogIndex
from app.schema import ContextDeeplinkResponse


BASE_URL = "http://localhost:8000"
API_URL = f"{BASE_URL}/v1/troubleshoot"

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "deeplinks.json"


# ---------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------

SCENARIOS = [
    {
        "name": "Wi-Fi scanning",
        "query": "Enable Wi-Fi scanning",
        "siis_response": {
            "title": "Wi-Fi scanning",
            "content": (
                "Enable Wi-Fi scanning via device Settings "
                "on the device."
            ),
        },
    },
    {
        "name": "Bluetooth",
        "query": "Enable Bluetooth",
        "siis_response": {
            "title": "Bluetooth",
            "content": (
                "Enable Bluetooth via device Settings "
                "on the device."
            ),
        },
    },
    {
        "name": "Battery",
        "query": "My battery is draining very fast",
        "siis_response": {
            "title": "Battery drain",
            "content": (
                "Check battery usage and follow the "
                "available battery troubleshooting guidance."
            ),
        },
    },
    {
        "name": "Display",
        "query": "My phone display is completely black",
        "siis_response": {
            "title": "Black screen",
            "content": (
                "Check the device display and follow the "
                "available troubleshooting guidance."
            ),
        },
    },
    {
        "name": "Charging",
        "query": "My phone is not charging",
        "siis_response": {
            "title": "Charging issue",
            "content": (
                "Check the charging connection and follow "
                "the available troubleshooting guidance."
            ),
        },
    },
    {
        "name": "Unseen scenario",
        "query": "My phone has a strange problem I cannot identify",
        "siis_response": {
            "title": "Unknown device issue",
            "content": (
                "Check the device and follow the available "
                "troubleshooting guidance."
            ),
        },
    },
]


PARAPHRASES = [
    "My Samsung phone screen is totally black",
    "The display on my phone has gone black",
    "My phone screen is blank and black",
    "I cannot see anything on my phone display",
    "My Samsung screen is not showing anything",
    "The phone display suddenly became black",
    "My screen went completely dark",
    "My phone has a black blank display",
    "Nothing is visible on my phone screen",
]


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def post(client: httpx.Client, payload: dict) -> tuple[dict, float]:
    start = time.perf_counter()

    response = client.post(
        API_URL,
        json=payload,
    )

    elapsed_ms = (time.perf_counter() - start) * 1000

    response.raise_for_status()

    return response.json(), elapsed_ms


def validate_response(
    response: dict,
    catalog: CatalogIndex,
) -> list[str]:
    errors: list[str] = []

    # Pydantic schema validation
    try:
        parsed = ContextDeeplinkResponse.model_validate(response)
    except Exception as exc:
        return [f"Schema validation failed: {exc}"]

    # URL leak check
    raw = json.dumps(response)

    if re.search(r"https?://", raw, re.IGNORECASE):
        errors.append("HTTP/HTTPS URL leak detected")

    # Goal validation
    for goal in parsed.contexts:
        if not goal.goal.startswith(
            "Follow these steps to perform this"
        ):
            errors.append("Invalid goal format")

        if not 0 <= goal.score <= 1:
            errors.append("Score outside 0-1")

        # Title should contain 2-3 words
        title_words = goal.title.split()

        if not 2 <= len(title_words) <= 3:
            errors.append(
                f"Title has {len(title_words)} words: {goal.title!r}"
            )

        for action in goal.actions:

            # Description rule
            if not action.description.startswith("It will"):
                errors.append(
                    f"Description does not start with 'It will': "
                    f"{action.description!r}"
                )

            # Category rule
            if action.category.value not in {
                "auto",
                "manual",
                "critical",
            }:
                errors.append(
                    f"Invalid category: {action.category}"
                )

            for group in action.stepGroups:

                if not group.steps:
                    errors.append("Empty step group")

                for step in group.steps:
                    if not step.strip():
                        errors.append("Blank troubleshooting step")

                # Auto actions should have actionable deeplink
                if action.category.value == "auto":
                    if group.actionableDeeplink is None:
                        errors.append(
                            "Auto action missing actionable deeplink"
                        )

                # Validate actionable deeplink against catalog
                if group.actionableDeeplink is not None:
                    uri = group.actionableDeeplink.deeplink

                    if not catalog.is_real_uri(uri):
                        errors.append(
                            f"Invalid actionable deeplink: {uri}"
                        )

                # Validate validation deeplink when present
                if group.validationDeeplink is not None:
                    uri = group.validationDeeplink.deeplink

                    if not catalog.is_real_validation_uri(uri):
                        errors.append(
                            f"Invalid validation deeplink: {uri}"
                        )

    return errors


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0

    values = sorted(values)

    index = (len(values) - 1) * p

    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    weight = index - lower

    return (
        values[lower]
        + (values[upper] - values[lower]) * weight
    )


def print_result(name: str, passed: bool, details: str = "") -> None:
    status = "PASS" if passed else "FAIL"

    print(
        f"[{status}] {name}"
        + (f" — {details}" if details else "")
    )


# ---------------------------------------------------------
# Main validation
# ---------------------------------------------------------

def main() -> None:
    print()
    print("=" * 70)
    print("TAPFIX — SAMSUNG PRISM HACKATHON VALIDATION")
    print("=" * 70)
    print()

    catalog = CatalogIndex.from_file(CATALOG_PATH)

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:

        # -------------------------------------------------
        # 1. Health
        # -------------------------------------------------

        try:
            response = client.get("/health")

            passed = (
                response.status_code == 200
                and response.json() == {"status": "ok"}
            )

            print_result(
                "Health check",
                passed,
                str(response.json()),
            )

        except Exception as exc:
            print_result(
                "Health check",
                False,
                str(exc),
            )
            return

        # -------------------------------------------------
        # 2. Core scenario validation
        # -------------------------------------------------

        print()
        print("-" * 70)
        print("CORE SCENARIOS")
        print("-" * 70)

        valid_count = 0
        url_leaks = 0
        deeplink_failures = 0
        scenario_latencies: list[float] = []

        for scenario in SCENARIOS:

            try:
                response, elapsed = post(
                    client,
                    {
                        "query": scenario["query"],
                        "siis_response": scenario["siis_response"],
                    },
                )

                scenario_latencies.append(elapsed)

                errors = validate_response(
                    response,
                    catalog,
                )

                if errors:
                    print_result(
                        scenario["name"],
                        False,
                        "; ".join(errors),
                    )
                else:
                    valid_count += 1

                    print_result(
                        scenario["name"],
                        True,
                        f"{elapsed:.1f} ms",
                    )

                raw = json.dumps(response)

                if re.search(
                    r"https?://",
                    raw,
                    re.IGNORECASE,
                ):
                    url_leaks += 1

                try:
                    parsed = ContextDeeplinkResponse.model_validate(
                        response
                    )

                    for goal in parsed.contexts:
                        for action in goal.actions:
                            for group in action.stepGroups:
                                if group.actionableDeeplink:
                                    if not catalog.is_real_uri(
                                        group.actionableDeeplink.deeplink
                                    ):
                                        deeplink_failures += 1

                                if group.validationDeeplink:
                                    if not catalog.is_real_validation_uri(
                                        group.validationDeeplink.deeplink
                                    ):
                                        deeplink_failures += 1

                except Exception:
                    pass

            except Exception as exc:
                print_result(
                    scenario["name"],
                    False,
                    str(exc),
                )

        coverage = (
            valid_count / len(SCENARIOS)
            if SCENARIOS
            else 0
        )

        print()
        print_result(
            "Scenario coverage",
            coverage >= 0.95,
            f"{valid_count}/{len(SCENARIOS)} "
            f"({coverage * 100:.1f}%)",
        )

        print_result(
            "Zero URL leaks",
            url_leaks == 0,
            f"{url_leaks} leaks",
        )

        print_result(
            "Deeplink validity",
            deeplink_failures == 0,
            f"{deeplink_failures} invalid deeplinks",
        )

        # -------------------------------------------------
        # 3. Unseen scenario
        # -------------------------------------------------

        unseen = SCENARIOS[-1]

        try:
            response, elapsed = post(
                client,
                {
                    "query": unseen["query"],
                    "siis_response": unseen["siis_response"],
                },
            )

            parsed = ContextDeeplinkResponse.model_validate(
                response
            )

            passed = len(parsed.contexts) > 0

            print_result(
                "Unseen scenario",
                passed,
                f"{elapsed:.1f} ms",
            )

        except Exception as exc:
            print_result(
                "Unseen scenario",
                False,
                str(exc),
            )

        # -------------------------------------------------
        # 4. Cache repeat-query test
        # -------------------------------------------------

        print()
        print("-" * 70)
        print("CACHE TEST")
        print("-" * 70)

        cache_payload = {
            "query": "My phone display is completely black",
            "siis_response": {
                "title": "Black screen",
                "content": (
                    "Check the device display and follow the "
                    "available troubleshooting guidance."
                ),
            },
        }

        # Warm up
        try:
            post(client, cache_payload)

            repeat_times: list[float] = []

            for _ in range(20):
                _, elapsed = post(
                    client,
                    cache_payload,
                )
                repeat_times.append(elapsed)

            p95 = percentile(
                repeat_times,
                0.95,
            )

            print_result(
                "Repeat-query p95 <= 300 ms",
                p95 <= 300,
                f"{p95:.1f} ms",
            )

        except Exception as exc:
            print_result(
                "Repeat-query latency",
                False,
                str(exc),
            )

        # -------------------------------------------------
        # 5. Paraphrase cache
        # -------------------------------------------------

        paraphrase_hits = 0

        for query in PARAPHRASES:
            payload = {
                "query": query,
                "siis_response": cache_payload["siis_response"],
            }

            try:
                response, _ = post(
                    client,
                    payload,
                )

                if response.get("contexts"):
                    paraphrase_hits += 1

            except Exception:
                pass

        paraphrase_rate = (
            paraphrase_hits / len(PARAPHRASES)
            if PARAPHRASES
            else 0
        )

        print_result(
            "Paraphrase coverage >= 80%",
            paraphrase_rate >= 0.80,
            f"{paraphrase_hits}/{len(PARAPHRASES)} "
            f"({paraphrase_rate * 100:.1f}%)",
        )

        # -------------------------------------------------
        # 6. Cold-start latency
        # -------------------------------------------------

        if scenario_latencies:
            cold_p95 = percentile(
                scenario_latencies,
                0.95,
            )

            print_result(
                "Cold-start p95 <= 8 seconds",
                cold_p95 <= 8000,
                f"{cold_p95:.1f} ms",
            )

        # -------------------------------------------------
        # 7. Query variations
        # -------------------------------------------------

        print()
        print("-" * 70)
        print("QUERY VARIATIONS")
        print("-" * 70)

        variations = [
            "Enable Wi-Fi scanning",
            "Turn Wi-Fi scanning on",
            "Switch Wi-Fi scanning on",
            "Please enable WiFi scanning",
            "Activate Wi-Fi scanning",
            "I want Wi-Fi scanning enabled",
            "Can you turn on Wi-Fi scanning",
            "Switch on WiFi scanning",
            "Make Wi-Fi scanning active",
            "Turn my Wi-Fi scanning on",
        ]

        variation_success = 0

        for query in variations:
            try:
                response, _ = post(
                    client,
                    {
                        "query": query,
                        "siis_response": {
                            "title": "Wi-Fi scanning",
                            "content": (
                                "Enable Wi-Fi scanning via device "
                                "Settings on the device."
                            ),
                        },
                    },
                )

                errors = validate_response(
                    response,
                    catalog,
                )

                if not errors:
                    variation_success += 1

            except Exception:
                pass

        print_result(
            "10 query variations valid",
            variation_success == 10,
            f"{variation_success}/10",
        )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print()
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()