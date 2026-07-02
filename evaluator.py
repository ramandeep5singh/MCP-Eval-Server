"""
evaluator.py — Pure metric calculation functions.

All functions are stateless and deterministic.
No I/O, no network calls, no side effects.
Input: raw data from MCP interactions.
Output: metric values (bool, int, float, str, None).
"""

import jsonschema


# Query types
QUERY_TYPE_TOOL = "tool_query"
QUERY_TYPE_DIRECT = "direct_answer"
QUERY_TYPE_IRRELEVANT = "irrelevant"

NO_TOOL_EXPECTED_TYPES = {QUERY_TYPE_DIRECT, QUERY_TYPE_IRRELEVANT}


# Bucket 1 — Tool Invocation
def calc_tool_called(tool_calls: list) -> bool:
    """True if at least one tool was invoked by the LLM."""
    return len(tool_calls) > 0


def calc_tool_input_schema_valid(tool_calls: list, expected_arg_schemas: list) -> bool:
    """
    True only if every tool call's arguments match its expected JSON schema.
    AND condition across all calls.
    """
    if not tool_calls:
        return False

    for call, schema in zip(tool_calls, expected_arg_schemas):
        if schema is None:
            continue
        try:
            jsonschema.validate(instance=call.get("arguments", {}), schema=schema)
        except jsonschema.ValidationError:
            return False

    return True


# Bucket 2 — Tool Execution
def calc_tool_execution_success(execution_results: list) -> bool:
    """True only if ALL tool executions succeeded. AND condition."""
    if not execution_results:
        return False
    return all(result.get("success", False) for result in execution_results)


def calc_tool_output_schema_valid(execution_results: list, expected_output_schemas: list) -> bool:
    """True only if ALL successful outputs match their expected schema. AND condition."""
    if not execution_results:
        return False

    all_valid = True
    for result, schema in zip(execution_results, expected_output_schemas):
        if not result.get("success", False):
            all_valid = False
            continue
        if schema is None:
            continue
        try:
            jsonschema.validate(instance=result.get("output", {}), schema=schema)
        except jsonschema.ValidationError:
            all_valid = False

    return all_valid


# Bucket 3 — Observation only
def calc_tool_call_count(tool_calls: list) -> int:
    return len(tool_calls)


def calc_tool_latency_ms(latencies_ms: list) -> float:
    """Average latency across all tool calls. 0.0 if no calls made."""
    if not latencies_ms:
        return 0.0
    return round(sum(latencies_ms) / len(latencies_ms), 2)


def calc_tool_error_type(execution_results: list) -> list | None:
    """Ordered list of error types per call. None if no errors occurred at all."""
    error_types = [r.get("error_type") for r in execution_results]
    return error_types if any(e is not None for e in error_types) else None


# Verdict
def calc_verdict(metrics: dict) -> str:
    """
    Overall pass/fail for the row.
    Pass only if every applicable (non-None) pass/fail metric is True.
    """
    pass_fail_keys = [
        "tool_called",
        "tool_input_schema_valid",
        "tool_execution_success",
        "tool_output_schema_valid",
        "no_tool_call_correct",
    ]

    for key in pass_fail_keys:
        value = metrics.get(key)
        if value is None:
            continue   # not applicable for this query type
        if value is False:
            return "fail"

    return "pass"


# Single entry point — orchestrator.py only calls this
def evaluate_row(
    tool_calls: list,
    execution_results: list,
    expected_arg_schemas: list,
    expected_output_schemas: list,
    latencies_ms: list,
    query_type: str = QUERY_TYPE_TOOL,
) -> dict:
    """
    Compute all metrics + verdict for one test case row.
    Returns a flat dict ready to be stored by orchestrator/report.
    """
    no_tool_called = len(tool_calls) == 0

    # -- direct_answer / irrelevant: no tool call expected --------------
    if query_type in NO_TOOL_EXPECTED_TYPES:
        metrics = {
            "query_type": query_type,
            "tool_called": calc_tool_called(tool_calls),
            "tool_call_count": calc_tool_call_count(tool_calls),
            "no_tool_call_correct": no_tool_called,
            "tool_input_schema_valid": None,
            "tool_execution_success": None,
            "tool_error_type": None,
            "tool_output_schema_valid": None,
            "tool_latency_ms": 0.0,
        }
        metrics["verdict"] = calc_verdict(metrics)
        return metrics

    # -- tool_query: tool call is required -------------------------------
    if no_tool_called:
        metrics = {
            "query_type": query_type,
            "tool_called": False,
            "tool_call_count": 0,
            "no_tool_call_correct": None,
            "tool_input_schema_valid": False,
            "tool_execution_success": False,
            "tool_error_type": None,
            "tool_output_schema_valid": False,
            "tool_latency_ms": 0.0,
        }
        metrics["verdict"] = calc_verdict(metrics)
        return metrics

    metrics = {
        "query_type": query_type,
        "tool_called": calc_tool_called(tool_calls),
        "tool_call_count": calc_tool_call_count(tool_calls),
        "no_tool_call_correct": None,
        "tool_input_schema_valid": calc_tool_input_schema_valid(tool_calls, expected_arg_schemas),
        "tool_execution_success": calc_tool_execution_success(execution_results),
        "tool_error_type": calc_tool_error_type(execution_results),
        "tool_output_schema_valid": calc_tool_output_schema_valid(execution_results, expected_output_schemas),
        "tool_latency_ms": calc_tool_latency_ms(latencies_ms),
    }
    metrics["verdict"] = calc_verdict(metrics)
    return metrics