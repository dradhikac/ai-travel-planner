"""Pytest configuration and category-level reporting for regression suite."""

from collections import defaultdict
from typing import Any

import pytest

# In-memory registry tracking regression test results by category
_REGRESSION_CATEGORY_RESULTS: dict[str, dict[str, int]] = defaultdict(
    lambda: {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
)


def record_category_result(category: str, outcome: str) -> None:
    """Record execution outcome for a regression category."""
    _REGRESSION_CATEGORY_RESULTS[category]["total"] += 1
    if outcome in ("passed", "failed", "skipped"):
        _REGRESSION_CATEGORY_RESULTS[category][outcome] += 1


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    """Capture test outcome during call phase to update category stats."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and "regression" in item.keywords:
        # Extract case category if available in call kwargs
        category = "general"
        if hasattr(item, "callspec") and "case" in item.callspec.params:
            case = item.callspec.params["case"]
            category = case.get("category", "general")

        if report.passed:
            record_category_result(category, "passed")
        elif report.failed:
            record_category_result(category, "failed")
        elif report.skipped:
            record_category_result(category, "skipped")


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: Any
) -> None:
    """Print clean category-by-category one-line summary at end of test run."""
    if not _REGRESSION_CATEGORY_RESULTS:
        return

    terminalreporter.write_sep("=", "Regression Suite Category Summary", bold=True)
    total_passed = 0
    total_all = 0

    for category, stats in sorted(_REGRESSION_CATEGORY_RESULTS.items()):
        passed = stats["passed"]
        total = stats["total"]
        total_passed += passed
        total_all += total
        pct = (passed / total * 100.0) if total > 0 else 0.0
        status_line = f"  {category:<24} : {passed}/{total} passed ({pct:5.1f}%)"
        if passed == total:
            terminalreporter.write_line(status_line, green=True)
        else:
            terminalreporter.write_line(status_line, red=True)

    terminalreporter.write_sep("-")
    overall_pct = (total_passed / total_all * 100.0) if total_all > 0 else 0.0
    summary_line = (
        f"  Total regression cases   : {total_passed}/{total_all} passed "
        f"({overall_pct:5.1f}%)"
    )
    terminalreporter.write_line(
        summary_line, bold=True, green=(total_passed == total_all)
    )
    terminalreporter.write_sep("=", bold=True)
