"""
app.py — Flask entry point for the MCP Eval Server.

Endpoints:
  POST /run    — Start a full evaluation run in the background.
  POST /proxy  — Hit by the agent (via N8N) instead of the real MCP server.
  POST /eval   — Hit by N8N with expected data; computes and stores metrics.

Shared state (single-run-at-a-time, since the orchestrator is strictly
sequential — only one query is ever "in flight"):
  - collector           : ReportCollector, shared by /eval and orchestrator.py
  - current_actual_data : holds the one active /proxy capture, read+cleared by /eval
  - mcp_client           : concrete BaseMCPClient implementation (None until chosen)
"""

import csv
import threading
from datetime import datetime

from flask import Flask, jsonify, request

import config
import evaluator
import orchestrator
import report

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

collector = report.ReportCollector()

current_actual_data = None
mcp_client = None


# POST /run
@app.route("/run", methods=["POST"])
def run():
    """
    Start a full evaluation run in the background.

    Body:
    {
        "test_file_path": "test_cases/weather_mcp_server.csv",
        "change_info": "Added retry logic to weather_mcp_client timeout handling"
    }
    """
    body = request.get_json(force=True)

    test_file_path = body.get("test_file_path")
    change_info = body.get("change_info", "")

    if not test_file_path:
        return jsonify({"error": "test_file_path is required"}), 400

    try:
        test_cases = _read_test_csv(test_file_path)
    except FileNotFoundError:
        return jsonify({"error": f"File not found: {test_file_path}"}), 400
    except Exception as exc:
        return jsonify({"error": f"Failed to read CSV: {exc}"}), 400

    if not test_cases:
        return jsonify({"error": "No test cases found in CSV"}), 400

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    thread = threading.Thread(
        target=orchestrator.run_evaluation,
        args=(test_cases, change_info, run_id, collector),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "status": "started",
        "message": f"Evaluation started. {len(test_cases)} test cases loaded.",
        "run_id": run_id,
    }), 200


def _read_test_csv(path: str) -> list:
    """Read the test CSV directly from the server's filesystem."""
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


# POST /proxy
@app.route("/proxy", methods=["POST"])
def proxy():
    """
    Intercepts a tools/call JSON-RPC request from the agent, forwards it to
    the real MCP server via mcp_client, and returns the real response
    untouched. Captures actual tool_name/arguments/output/latency along
    the way for /eval to use.
    """
    global current_actual_data

    if mcp_client is None:
        return jsonify({
            "error": {
                "code": -32000,
                "message": "No MCP client configured yet. Implement and set mcp_client in app.py."
            }
        }), 501

    body = request.get_json(force=True)
    params = body.get("params", {})
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    result = mcp_client.call_tool(tool_name, arguments)

    current_actual_data = {
        "tool_calls": [{"name": tool_name, "arguments": arguments}],
        "execution_results": [result],
        "latencies_ms": [result["latency_ms"]],
    }

    if result["success"]:
        return jsonify({
            "jsonrpc": config.JSONRPC_VERSION,
            "id": body.get("id"),
            "result": {
                "content": [{"type": "text", "text": str(result["output"])}]
            },
        }), 200
    else:
        return jsonify({
            "jsonrpc": config.JSONRPC_VERSION,
            "id": body.get("id"),
            "error": {"message": result["error_type"]},
        }), 200


# POST /eval
def eval_endpoint():
    """
    Receives expected data from N8N, combines it with the actual data
    captured by /proxy, computes metrics, stores the result, and returns
    the full metrics dict (consumed by orchestrator.py via N8N's
    Respond to Webhook node).
    """
    global current_actual_data

    body = request.get_json(force=True)

    query = body.get("query", "")
    query_type = body.get("query_type", evaluator.QUERY_TYPE_TOOL)
    expected_arg_schema = body.get("expected_arg_schema")
    expected_output_schema = body.get("expected_output_schema")
    expected_tool = body.get("expected_tool")

    actual = current_actual_data or {
        "tool_calls": [],
        "execution_results": [],
        "latencies_ms": [],
    }

    metrics = evaluator.evaluate_row(
        tool_calls=actual["tool_calls"],
        execution_results=actual["execution_results"],
        expected_arg_schemas=_to_list(expected_arg_schema),
        expected_output_schemas=_to_list(expected_output_schema),
        latencies_ms=actual["latencies_ms"],
        query_type=query_type,
    )

    row = {
        "query": query,
        "expected_tool": expected_tool,
        **metrics,
    }
    collector.add_result(row)

    # Reset — ready for the next query in the sequence
    current_actual_data = None

    return jsonify(row), 200


def _to_list(value) -> list:
    """Wrap a single schema dict in a list; leave lists alone; turn None to []."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

# Run
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)