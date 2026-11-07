#!/usr/bin/env python3
"""Cross-platform smoke test script for AI Travel Concierge.

Verifies running service instances using only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def check_url(url: str, timeout_seconds: float = 5.0) -> tuple[int, bytes]:
    """Perform HTTP GET request using urllib and return status code and body."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json, text/html, */*"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        status_code: int = response.status
        body: bytes = response.read()
        return status_code, body


def run_smoke_tests(backend_url: str, frontend_url: str | None = None) -> bool:
    """Run smoke checks against backend and optional frontend endpoints."""
    all_passed = True
    backend_base = backend_url.rstrip("/")

    print("=== AI Travel Concierge Smoke Test ===")
    print(f"Target Backend:  {backend_base}")
    if frontend_url:
        print(f"Target Frontend: {frontend_url.rstrip('/')}")
    print("--------------------------------------")

    # Check 1: Backend /health
    health_url = f"{backend_base}/health"
    try:
        status, body = check_url(health_url)
        data: Any = json.loads(body.decode("utf-8"))
        if status == 200 and isinstance(data, dict) and data.get("status") == "ok":
            print(f"[PASS] Backend /health -> HTTP {status} (status: 'ok')")
        else:
            print(
                f"[FAIL] Backend /health -> Expected status 'ok', got HTTP {status}: {data}"
            )
            all_passed = False
    except urllib.error.HTTPError as exc:
        print(f"[FAIL] Backend /health -> HTTP error {exc.code}: {exc.reason}")
        all_passed = False
    except urllib.error.URLError as exc:
        print(f"[FAIL] Backend /health -> Connection error: {exc.reason}")
        all_passed = False
    except json.JSONDecodeError:
        print("[FAIL] Backend /health -> Failed to parse JSON response")
        all_passed = False
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Backend /health -> Unexpected error: {exc}")
        all_passed = False

    # Check 2: Backend /api/version
    version_url = f"{backend_base}/api/version"
    try:
        status, body = check_url(version_url)
        data = json.loads(body.decode("utf-8"))
        if (
            status == 200
            and isinstance(data, dict)
            and isinstance(data.get("name"), str)
            and bool(data["name"].strip())
            and isinstance(data.get("version"), str)
            and bool(data["version"].strip())
            and isinstance(data.get("environment"), str)
            and bool(data["environment"].strip())
        ):
            print(
                f"[PASS] Backend /api/version -> HTTP {status} "
                f"(name='{data['name']}', version='{data['version']}', env='{data['environment']}')"
            )
        else:
            print(f"[FAIL] Backend /api/version -> Invalid payload structure: {data}")
            all_passed = False
    except urllib.error.HTTPError as exc:
        print(f"[FAIL] Backend /api/version -> HTTP error {exc.code}: {exc.reason}")
        all_passed = False
    except urllib.error.URLError as exc:
        print(f"[FAIL] Backend /api/version -> Connection error: {exc.reason}")
        all_passed = False
    except json.JSONDecodeError:
        print("[FAIL] Backend /api/version -> Failed to parse JSON response")
        all_passed = False
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Backend /api/version -> Unexpected error: {exc}")
        all_passed = False

    # Check 3: Frontend (optional)
    if frontend_url:
        fe_url = frontend_url.rstrip("/")
        try:
            status, _ = check_url(fe_url)
            if status == 200:
                print(f"[PASS] Frontend at {fe_url} -> HTTP {status}")
            else:
                print(f"[FAIL] Frontend at {fe_url} -> Expected HTTP 200, got {status}")
                all_passed = False
        except urllib.error.HTTPError as exc:
            print(f"[FAIL] Frontend -> HTTP error {exc.code}: {exc.reason}")
            all_passed = False
        except urllib.error.URLError as exc:
            print(f"[FAIL] Frontend -> Connection error: {exc.reason}")
            all_passed = False
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] Frontend -> Unexpected error: {exc}")
            all_passed = False

    print("--------------------------------------")
    if all_passed:
        print("[OVERALL] All smoke checks passed successfully.")
    else:
        print("[OVERALL] Smoke checks failed.")

    return all_passed


def main() -> int:
    """Parse CLI arguments and run smoke tests."""
    parser = argparse.ArgumentParser(
        description="Smoke test script for AI Travel Concierge services."
    )
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        help="Base URL of backend service (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--frontend-url",
        default=None,
        help="Optional base URL of frontend service (e.g. http://localhost:3000)",
    )

    args = parser.parse_args()
    success = run_smoke_tests(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
