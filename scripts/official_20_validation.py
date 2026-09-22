import json
import time
import requests
from pathlib import Path

BASE_URL = "http://localhost:8000"
DATA_FILE = Path("data/siis_responses.json")
DEEPLINK_FILE = Path("data/deeplinks.json")


def load_data():
    with DATA_FILE.open(encoding="utf-8") as f:
        data = json.load(f)

    with DEEPLINK_FILE.open(encoding="utf-8") as f:
        deeplinks = json.load(f)

    return data["responses"], deeplinks


def extract_real_uris(deeplinks):
    uris = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "deeplink" and isinstance(item, str):
                    if item.startswith("bixby://"):
                        uris.add(item)
                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(deeplinks)
    return uris


def check_health():
    response = requests.get(f"{BASE_URL}/health", timeout=10)

    if response.status_code != 200:
        raise RuntimeError(
            f"Health check failed: {response.status_code} {response.text}"
        )

    body = response.json()

    if body.get("status") != "ok":
        raise RuntimeError(f"Unexpected health response: {body}")

    print("[PASS] Health check")


def validate_response_shape(body):
    if not isinstance(body, dict):
        return False, "Response is not an object"

    if "contexts" not in body:
        return False, "Missing contexts"

    if not isinstance(body["contexts"], list):
        return False, "contexts is not a list"

    for context in body["contexts"]:
        required = {"goal", "title", "actions", "score"}

        if not required.issubset(context):
            return False, "Goal missing required fields"

        if not isinstance(context["actions"], list):
            return False, "actions is not a list"

        for action in context["actions"]:
            for field in ["actionName", "description", "stepGroups", "category"]:
                if field not in action:
                    return False, f"Action missing {field}"

            if action["category"] not in {"auto", "manual", "critical"}:
                return False, f"Invalid category: {action['category']}"

            if not isinstance(action["stepGroups"], list):
                return False, "stepGroups is not a list"

            for group in action["stepGroups"]:
                if not isinstance(group.get("steps"), list):
                    return False, "steps is not a list"

                if not group["steps"]:
                    return False, "Empty steps"

    return True, ""


def find_deeplinks(value):
    found = []

    if isinstance(value, dict):
        for key, item in value.items():
            if key == "deeplink" and isinstance(item, str):
                found.append(item)
            else:
                found.extend(find_deeplinks(item))

    elif isinstance(value, list):
        for item in value:
            found.extend(find_deeplinks(item))

    return found


def find_url_leaks(value):
    leaks = []

    if isinstance(value, dict):
        for key, item in value.items():
            leaks.extend(find_url_leaks(item))

    elif isinstance(value, list):
        for item in value:
            leaks.extend(find_url_leaks(item))

    elif isinstance(value, str):
        lowered = value.lower()

        if (
            "http://" in lowered
            or "https://" in lowered
            or "www." in lowered
        ):
            leaks.append(value)

    return leaks


def main():
    print("=" * 70)
    print("TAPFIX — OFFICIAL SAMSUNG 20-SCENARIO VALIDATION")
    print("=" * 70)

    scenarios, deeplinks = load_data()
    real_uris = extract_real_uris(deeplinks)

    print(f"\nOfficial scenarios loaded: {len(scenarios)}")
    print(f"Catalog deeplinks found: {len(real_uris)}")

    check_health()

    print("\n" + "-" * 70)
    print("20 OFFICIAL SCENARIOS")
    print("-" * 70)

    passed = 0
    schema_passed = 0
    invalid_deeplinks = []
    url_leaks = []
    failures = []

    latencies = []

    for index, item in enumerate(scenarios, 1):
        query = item["original_query"]
        siis = item["siis_response"]

        payload = {
            "query": query,
            "siis_response": siis,
        }

        start = time.perf_counter()

        try:
            response = requests.post(
                f"{BASE_URL}/v1/troubleshoot",
                json=payload,
                timeout=15,
            )

            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

            if response.status_code != 200:
                failures.append(
                    f"{index}: HTTP {response.status_code}"
                )
                print(
                    f"[FAIL] {index:02d} — HTTP {response.status_code} "
                    f"({elapsed_ms:.1f} ms)"
                )
                continue

            body = response.json()

            # Schema checks
            valid, reason = validate_response_shape(body)

            if valid:
                schema_passed += 1
            else:
                failures.append(f"{index}: {reason}")
                print(
                    f"[FAIL] {index:02d} — {reason} "
                    f"({elapsed_ms:.1f} ms)"
                )
                continue

            # Deeplink checks
            scenario_invalid = []

            for uri in find_deeplinks(body):
                if uri == "bixby://dummy_positive":
                    continue

                if uri not in real_uris:
                    scenario_invalid.append(uri)

            if scenario_invalid:
                invalid_deeplinks.extend(
                    (index, uri) for uri in scenario_invalid
                )

            # URL leak checks
            scenario_leaks = find_url_leaks(body)

            if scenario_leaks:
                url_leaks.extend(
                    (index, leak) for leak in scenario_leaks
                )

            passed += 1

            print(
                f"[PASS] {index:02d} — "
                f"{elapsed_ms:.1f} ms"
            )

        except Exception as exc:
            failures.append(f"{index}: {type(exc).__name__}: {exc}")

            print(
                f"[FAIL] {index:02d} — "
                f"{type(exc).__name__}: {exc}"
            )

    coverage = (passed / len(scenarios)) * 100

    print("\n" + "-" * 70)
    print("OFFICIAL GATES")
    print("-" * 70)

    print(
        f"[{'PASS' if coverage >= 95 else 'FAIL'}] "
        f"G3 Scenario coverage — "
        f"{passed}/{len(scenarios)} ({coverage:.1f}%)"
    )

    print(
        f"[{'PASS' if schema_passed / len(scenarios) >= 0.90 else 'FAIL'}] "
        f"G4 Schema validity — "
        f"{schema_passed}/{len(scenarios)} "
        f"({schema_passed / len(scenarios) * 100:.1f}%)"
    )

    print(
        f"[{'PASS' if not url_leaks else 'FAIL'}] "
        f"G5 Zero URL leaks — "
        f"{len(url_leaks)} leaks"
    )

    print(
        f"[{'PASS' if not invalid_deeplinks else 'FAIL'}] "
        f"Deeplink validity — "
        f"{len(invalid_deeplinks)} invalid deeplinks"
    )

    if latencies:
        sorted_latencies = sorted(latencies)

        p95_index = max(
            0,
            min(
                len(sorted_latencies) - 1,
                int(len(sorted_latencies) * 0.95) - 1,
            ),
        )

        p95 = sorted_latencies[p95_index]

        print(
            f"[INFO] Official 20-query latency p95 — "
            f"{p95:.1f} ms"
        )

    print("\n" + "-" * 70)
    print("FAILURE DETAILS")
    print("-" * 70)

    if not failures:
        print("No scenario failures.")

    else:
        for failure in failures:
            print(f"- {failure}")

    if invalid_deeplinks:
        print("\nInvalid deeplinks:")

        for index, uri in invalid_deeplinks:
            print(f"- Scenario {index}: {uri}")

    if url_leaks:
        print("\nURL leaks:")

        for index, leak in url_leaks:
            print(f"- Scenario {index}: {leak}")

    print("\n" + "=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()