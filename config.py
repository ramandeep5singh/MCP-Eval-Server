"""
config.py — Central configuration for the MCP Eval Server.
All values live here. Nothing is hardcoded elsewhere.

Two kinds of values:
  1. Secrets / environment-specific  → read from environment variables
  2. Fixed project settings          → plain constants
"""

import os

# Secrets & environment-specific values (env vars)
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000")
N8N_AGENT_WEBHOOK_URL = os.getenv("N8N_AGENT_WEBHOOK_URL", "")
N8N_OPTIMIZER_WEBHOOK_URL = os.getenv("N8N_OPTIMIZER_WEBHOOK_URL", "")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

# LLM settings — fixed project decisions, plain constants
LLM_MODEL = "gpt-40-mini"
LLM_MAX_TOKENS = 1024
LLM_TEMPERATURE = 0

# File paths — fixed project structure, plain constants
REPORTS_DIR = "reports"
RUNS_INDEX_PATH = "runs_index.json"

# HTTP — fixed tuning value, plain constant
MCP_REQUEST_TIMEOUT = 30

# JSON-RPC — protocol constants, never change
JSONRPC_VERSION = "2.0"
JSONRPC_TOOL_CALL_METHOD = "tools/call"
JSONRPC_TOOL_LIST_METHOD = "tools/list"