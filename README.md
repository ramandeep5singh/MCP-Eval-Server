# MCP Eval Server

A Flask-based evaluation server for testing MCP (Model Context Protocol) server tools using deterministic metrics. It works by sitting between an AI agent and a real MCP server — intercepting tool calls, forwarding them unchanged, and measuring what actually happened against what was expected.

> **Status: Early Development** — Core proxy and evaluation architecture is complete. MCP server target and agent system prompt are not yet finalized. See [Deferred](#deferred) section.

---

## What It Does

Most LLM evaluation frameworks judge outputs using another LLM. This project takes a different approach: **deterministic metrics only**. Every metric is computed from observable facts — did the tool get called, did the schema match, did execution succeed, how long did it take — with no LLM involved in scoring.

The result is an evaluation pipeline that is reproducible, cheap to run, and produces structured failure data that tells you exactly which metric failed and why, rather than a score you have to interpret.

---

## How It Works

```
Postman → POST /run (test_file_path + change_info)
  → Flask responds immediately: "evaluation started"
  → orchestrator.py runs in background thread
  → loop, one row at a time:
       → POST row to N8N agent webhook (BLOCKS waiting for response)
       → N8N feeds query to Search Agent (LLM + Memory + MCP Client tool)
       → Agent's MCP Client is configured to call POST /proxy
         instead of the real MCP server
       → /proxy captures actual tool_name + arguments,
         forwards to real MCP server via mcp_client.call_tool(),
         captures output / success / error_type / latency_ms,
         returns real response to agent untouched
       → N8N separately sends expected data to POST /eval
       → /eval reads /proxy captured data + N8N expected data,
         calls evaluator.evaluate_row(),
         stores result via shared ReportCollector,
         clears /proxy data,
         returns full metrics dict (verdict + reasons)
       → N8N relays /eval response back to orchestrator
       → orchestrator prints: [n/total] query → PASS/FAIL (+ reason)
       → on ANY error: print exact error, pause via input(),
         wait for user confirmation, retry same row — never skip
  → after loop: print summary,
    collector.finalize() writes both CSVs + appends to runs_index.json,
    sends diagnosis report to Optimizer webhook,
    collector.reset()
```

The orchestrator is **strictly sequential** — one row fully completes before the next begins. This is what makes `/proxy` safe with a single shared "current actual data" store and no correlation ID needed.

---

## File Structure

```
mcp_eval_server/
├── app.py                          # Flask app, endpoint registration
├── config.py                       # Constants and env vars
├── evaluator.py                    # Pure metric logic — no I/O
├── report.py                       # ReportCollector — CSV writing, runs_index
├── orchestrator.py                 # Background evaluation loop
├── mcp_client/
│   ├── base_client.py              # Abstract base class for MCP clients
│   └── weather_mcp_client.py       # ⏳ Deferred — MCP server not yet chosen
├── test_cases/
│   └── weather_mcp_server.csv      # Test cases (query, query_type, expected)
├── reports/                        # Auto-generated evaluation and diagnosis CSVs
└── runs_index.json                 # Flat run history, appended per run
```

---

## Endpoints

### `POST /run`
Starts an evaluation run. Returns immediately, runs in background.

**Request:**
```json
{
  "test_file_path": "test_cases/weather_mcp_server.csv",
  "change_info": "Added retry logic to weather_mcp_client timeout handling"
}
```

**Response (immediate):**
```json
{
  "status": "started",
  "message": "Evaluation started. 9 test cases loaded.",
  "run_id": "20250615_143022"
}
```

---

### `POST /proxy`
Hit by the agent's MCP Client instead of the real MCP server. Accepts a standard JSON-RPC `tools/call` request, forwards it to the real MCP server, captures the result, and returns the real response untouched.

Returns `501` if no MCP client is configured — allowing `/run` and `/eval` to be tested independently without a live MCP server.

---

### `POST /eval`
Hit by N8N with the expected data for the current row. Reads `/proxy`'s captured actual data, computes all metrics, stores the result, clears `/proxy` state, and returns the full metrics dict.

**Response example:**
```json
{
  "verdict": "fail",
  "query": "What is the weather in Berlin?",
  "query_type": "tool_query",
  "tool_called": true,
  "tool_call_count": 1,
  "no_tool_call_correct": null,
  "tool_input_schema_valid": true,
  "tool_execution_success": false,
  "tool_error_type": ["timeout"],
  "tool_output_schema_valid": false,
  "tool_latency_ms": 5000.0
}
```

---

## Query Types

Every test case is assigned one of three types, which determines which metrics apply:

| Type | What it tests |
|---|---|
| `tool_query` | LLM must call the correct tool with valid arguments |
| `direct_answer` | LLM must answer without calling any tool |
| `irrelevant` | Out-of-domain query — LLM must not call any tool |

---

## Metrics

### Pass / Fail
These determine the verdict. A test case passes only if all applicable (non-`null`) metrics are `True`.

| Metric | Applies to |
|---|---|
| `tool_called` | `tool_query` |
| `tool_input_schema_valid` | `tool_query` |
| `tool_execution_success` | `tool_query` |
| `tool_output_schema_valid` | `tool_query` |
| `no_tool_call_correct` | `direct_answer`, `irrelevant` |

### Observation Only
These are captured for diagnosis and optimization — they do not affect verdict.

| Metric | Description |
|---|---|
| `tool_call_count` | How many tool calls the agent made |
| `tool_latency_ms` | Round-trip time for the MCP tool call |
| `tool_error_type` | List of error types if execution failed |

---

## Reports

Each completed run produces:

**Evaluation report CSV** — all rows with full metrics. Stored in `reports/`.

**Diagnosis report CSV** — failed rows only, with verdict reasons. Stored in `reports/` and also sent to the Optimizer webhook for the next iteration.

**`runs_index.json`** — flat file, one entry appended per run:
```json
{
  "run_id": "20250615_143022",
  "change_info": "Added retry logic to weather_mcp_client timeout handling",
  "total_test_cases": 9,
  "passed": 6,
  "failed": 3,
  "pass_rate": 0.667,
  "metric_failures": {
    "tool_execution_success": 2,
    "tool_output_schema_valid": 1
  },
  "evaluation_report": "reports/eval_20250615_143022.csv",
  "diagnosis_report": "reports/diag_20250615_143022.csv"
}
```

`metric_failures` breaks down exactly which metric failed and how many times across the run — this is the primary signal for what to fix next.

---

## Setup

### Requirements
```
flask
requests
jsonschema
```

Install:
```bash
pip install flask requests jsonschema
```

### Environment Variables
Set these before running:

```bash
export LLM_API_KEY=...
export MCP_SERVER_URL=...
export N8N_AGENT_WEBHOOK_URL=...
export N8N_OPTIMIZER_WEBHOOK_URL=...
```

### Run the server
```bash
python app.py
```

Server starts on `http://localhost:5000`.

---

## Key Design Decisions

**No LLM-as-a-judge.** Every metric is computed from observable facts intercepted at the proxy layer. Results are reproducible and cheap.

**Strictly sequential orchestration.** The orchestrator processes one row at a time and blocks until it completes. This eliminates the need for a correlation ID on `/proxy`'s shared data store and keeps failure handling simple.

**N8N hosts the agent, not the loop.** An earlier design had N8N driving the orchestration loop — this caused memory crashes under load. N8N now only hosts the Search Agent being tested and is triggered one row at a time by the orchestrator.

**`evaluator.py` and `report.py` are pure.** They have no I/O and no dependency on the Flask app or N8N. This is what allowed the architecture to pivot from an N8N-driven loop to an orchestrator-driven loop without touching either file.

**`/proxy` returns `501` gracefully.** When no MCP client is configured, the proxy returns a `501 Not Implemented` instead of crashing. This keeps `/run` and `/eval` independently testable during early development.

**No `get_expected_output_schema()` in `base_client.py`.** Expected output schema lives in the CSV. Duplicating it in the client would create two sources of truth for the same data.

---

## Deferred

These are not yet implemented and will be addressed in the next phase:

- **`any_mcp_client.py`** — concrete MCP client implementation, waiting on MCP server selection
- **LLM system prompt for the Search Agent** — not yet finalized
- **Phase 2 and Phase 3** — to be re-planned after Phase 1 is proven

---

## Project Context

This is Phase 1 of a larger evaluation and optimization pipeline. The diagnosis report produced by each run is designed to feed into a separate System Prompt Optimizer that uses it to generate an improved agent prompt — closing the loop between evaluation and optimization without manual intervention.
