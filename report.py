"""
report.py — Collects evaluation results in memory, writes the two CSV
reports at the end of a run, and appends one entry to runs_index.json.

No metric logic here. That belongs in evaluator.py.
This file only stores and writes.
"""

import csv
import json
import os
from datetime import datetime

import config


# Column order for both CSV reports
CSV_COLUMNS = [
    "query",
    "query_type",
    "expected_tool",
    "tool_called",
    "tool_call_count",
    "no_tool_call_correct",
    "tool_input_schema_valid",
    "tool_execution_success",
    "tool_error_type",
    "tool_output_schema_valid",
    "tool_latency_ms",
    "verdict",
]

# Metrics tracked individually in runs_index.json
TRACKED_METRICS = [
    "tool_called",
    "tool_input_schema_valid",
    "tool_execution_success",
    "tool_output_schema_valid",
    "no_tool_call_correct",
]


class ReportCollector:
    """
    Holds all result rows for one eval run in memory.

    Usage:
        collector = ReportCollector()
        collector.add_result(row)          # called once per test case
        summary = collector.finalize(change_info, run_id)
    """

    def __init__(self):
        self._rows: list[dict] = []

    def add_result(self, row: dict) -> None:
        """Append one evaluated test case result."""
        self._rows.append(row)

    def row_count(self) -> int:
        return len(self._rows)

    # End of run — write both CSVs + append to runs_index.json
    def finalize(self, change_info: str, run_id: str = None) -> dict:
        """
        Write evaluation report CSV, diagnosis report CSV, and append
        a summary entry to runs_index.json.

        Returns the summary dict that was appended to runs_index.json
        (orchestrator needs evaluation_report / diagnosis_report paths
        and the diagnosis rows to send to the N8N webhook).
        """
        os.makedirs(config.REPORTS_DIR, exist_ok=True)

        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        eval_path = os.path.join(config.REPORTS_DIR, f"eval_{run_id}.csv")
        diag_path = os.path.join(config.REPORTS_DIR, f"diag_{run_id}.csv")

        fail_rows = [r for r in self._rows if r.get("verdict") == "fail"]

        self._write_csv(eval_path, self._rows)
        self._write_csv(diag_path, fail_rows)

        summary = self._build_summary(
            run_id=run_id,
            change_info=change_info,
            eval_path=eval_path,
            diag_path=diag_path,
            fail_rows=fail_rows,
        )

        self._append_to_runs_index(summary)

        return summary

    def reset(self) -> None:
        """Clear all stored rows. Call after finalize() if reusing the collector."""
        self._rows = []

    # Private helpers
    def _write_csv(self, filepath: str, rows: list[dict]) -> None:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _build_summary(self, run_id, change_info, eval_path, diag_path, fail_rows) -> dict:
        total = len(self._rows)
        failed = len(fail_rows)
        passed = total - failed
        pass_rate = round((passed / total) * 100, 2) if total > 0 else 0.0

        metric_failures = {metric: 0 for metric in TRACKED_METRICS}
        for row in self._rows:
            for metric in TRACKED_METRICS:
                if row.get(metric) is False:
                    metric_failures[metric] += 1

        return {
            "run_id": run_id,
            "change_info": change_info,
            "total_test_cases": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate,
            "metric_failures": metric_failures,
            "evaluation_report": eval_path,
            "diagnosis_report": diag_path,
        }

    def _append_to_runs_index(self, summary: dict) -> None:
        """Append summary to runs_index.json. Creates the file if missing."""
        path = config.RUNS_INDEX_PATH

        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    runs = json.load(f)
                except json.JSONDecodeError:
                    runs = []
        else:
            runs = []

        runs.append(summary)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=2)