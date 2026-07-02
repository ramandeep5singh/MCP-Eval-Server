"""
mcp_client/base_client.py — Abstract base class for all MCP clients.

Every MCP server integration must subclass BaseMCPClient and implement
call_tool() and get_tool_list(). This keeps orchestrator.py decoupled
from server-specific communication details.

Adding a new MCP server = new file in mcp_client/ + new test CSV.
Zero changes needed in orchestrator.py, evaluator.py, or report.py.
"""

from abc import ABC, abstractmethod


class BaseMCPClient(ABC):
    """
    Defines the interface every MCP client must satisfy.

    Concrete clients handle:
    - How to format the JSON-RPC request for their specific MCP server
    - How to parse and normalize the JSON-RPC response into a common shape
    """

    @abstractmethod
    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Send a single tools/call JSON-RPC request to the MCP server.

        Must return a normalized dict:
        {
            "success": bool,          # True if no error field in response
            "output": dict | None,    # parsed result content (if success)
            "error_type": str | None, # e.g. "invalid_params", "timeout"
            "latency_ms": float,      # wall-clock time for the round-trip
        }
        """

    @abstractmethod
    def get_tool_list(self) -> list:
        """
        Call tools/list on the MCP server.
        Returns a list of tool definition dicts as returned by the server.
        """