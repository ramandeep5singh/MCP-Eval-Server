"""
orchestrator.py — Drives one full evaluation run.

Responsibilities:
- Loop through test cases one at a time
- For each row, trigger the N8N agent webhook and wait for the result
  (N8N -> Search Agent -> /proxy -> real MCP server -> /proxy -> N8N -> /eval -> back here)
- Print live CLI progress (pass/fail + failure reason)
- On any error, pause, show the exact error, wait for user confirmation, retry the same row
- At the end of the run, finalize reports and notify the Optimizer webhook

This file does not call /proxy or /eval directly, and does not store
results itself — /eval already does that via the shared ReportCollector.
"""

import requests

import config


def run_evaluation(test_cases: list, change_info: str, run_id: str, collector) -> None:
    """
    Run the full evaluation loop for one /run request.

    test_cases : list of dicts parsed from the test CSV
    change_info: description of what changed before this run
    run_id     : identifier for this run, used in report filenames
    collector  : shared ReportCollector instance (same one /eval writes to)
    """
    total = len(test_cases)
    print(f"\n[Eval Server] Evaluation started — run_id={run_id} — {total} test cases loaded\n")

    passed = 0
    failed = 0

    for index, row in enumerate(test_cases, start=1):
        query = row.get("query", "")
        result = _run_row_with_retry(row, index, total)

        if result["verdict"] == "pass":
            passed += 1
            print(f"[{index}/{total}] \"{query}\" → PASS")
        else:
            failed += 1
            print(f"[{index}/{total}] \"{query}\" → FAIL")
            _print_failure_reason(result)

    print(f"\nRun complete — {passed} passed, {failed} failed\n")

    # Finalize reports
    summary = collector.finalize(change_info, run_id)
    print(f"Evaluation report saved → {summary['evaluation_report']}")
    print(f"Diagnosis report saved  → {summary['diagnosis_report']}")

    # Send diagnosis report to Optimizer webhook
    _send_diagnosis_to_optimizer(summary)

    collector.reset()


# Per-row execution with pause-and-retry on error
def _run_row_with_retry(row: dict, index: int, total: int) -> dict:
    """
    Send one row to the N8N agent webhook and wait for the /eval result.
    On any error, pause, print the exact error, wait for user confirmation,
    then retry the same row. Never advances until this row succeeds.
    """
    while True:
        try:
            return _send_row_to_n8n(row)
        except Exception as exc:
            print(f"\n[{index}/{total}] \"{row.get('query', '')}\" → ERROR\n")
            print("  Something went wrong:")
            print(f"  {type(exc).__name__}: {exc}\n")
            input("  Fix the issue, then press Enter to retry this row...")
            print(f"\n  Retrying [{index}/{total}]...\n")


def _send_row_to_n8n(row: dict) -> dict:
    """
    POST the row to the N8N agent webhook and return the /eval metrics dict
    that comes back through N8N's Respond to Webhook node.
    """
    payload = {
        "query": row.get("query"),
        "query_type": row.get("query_type"),
        "expected_tool": row.get("expected_tool"),
        "expected_arg_schema": row.get("expected_arg_schema"),
        "expected_output_schema": row.get("expected_output_schema"),
    }

    response = requests.post(
        config.N8N_AGENT_WEBHOOK_URL,
        json=payload,
        timeout=config.MCP_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# CLI helpers
def _print_failure_reason(result: dict) -> None:
    """Print which metric(s) failed for a row, straight from the /eval response."""
    checks = [
        "tool_called",
        "tool_input_schema_valid",
        "tool_execution_success",
        "tool_output_schema_valid",
        "no_tool_call_correct",
    ]
    for key in checks:
        value = result.get(key)
        if value is False:
            error_type = result.get("tool_error_type")
            suffix = f" (error: {error_type})" if error_type else ""
            print(f"        └─ {key}: False{suffix}")


# Optimizer webhook
def _send_diagnosis_to_optimizer(summary: dict) -> None:
    """Send the diagnosis report path/content to the Optimizer Agent webhook."""
    if not config.N8N_OPTIMIZER_WEBHOOK_URL:
        print("N8N_OPTIMIZER_WEBHOOK_URL not set — skipping diagnosis delivery.")
        return

    try:
        response = requests.post(
            config.N8N_OPTIMIZER_WEBHOOK_URL,
            json=summary,
            timeout=config.MCP_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        print("Diagnosis report delivered successfully to Optimizer Agent.")
    except Exception as exc:
        print(f"Failed to deliver diagnosis report: {type(exc).__name__}: {exc}")