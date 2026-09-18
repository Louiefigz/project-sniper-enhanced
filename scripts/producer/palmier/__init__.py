"""palmier — push a gated edit_plan.json into Palmier Pro over local MCP.

The destination leg of the pipeline (docs/PIPELINE.md): the plan stays the
determinism boundary; this package translates it into Palmier tool calls.

- ``mcp_client``  — plain HTTP JSON-RPC client for the app's MCP server
- ``translate``   — PURE plan+manifest → ordered step list (all the math)
- ``push``        — CLI executor: pre-render graphics, connect, run steps
"""
