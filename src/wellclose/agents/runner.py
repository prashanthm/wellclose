"""Strands agent runner (ADR-004): loads YAML specs -> strands Agent with LiteLLM model +
MCP tools from our gateway. Agent definitions are data; swapping frameworks is a contained
refactor (Brief §6.2). Requires the MCP server running (`wellclose mcp`) and the LiteLLM gateway."""
from __future__ import annotations
from pathlib import Path
import yaml
from ..config import settings

SPEC_DIR = Path(__file__).parent / "specs"


def load_spec(name: str) -> dict:
    return yaml.safe_load((SPEC_DIR / f"{name}.yaml").read_text())


def _model_id(alias: str) -> str:
    s = settings()
    return {"vision": s.model_vision, "text": s.model_text, "small": s.model_small}[alias]


def build_agent(spec_name: str, mcp_url: str = "http://localhost:8000/mcp"):
    """Returns (agent, mcp_client_context). Usage:
        agent, mcp_ctx = build_agent("historian_agent")
        with mcp_ctx:  # MUST stay open while the agent runs (strands MCP session)
            result = agent("Assemble history for well <id>; run_id=<rid>")
    """
    from strands import Agent
    from strands.models.litellm import LiteLLMModel
    from strands.tools.mcp import MCPClient
    from mcp.client.streamable_http import streamablehttp_client

    spec = load_spec(spec_name)
    s = settings()
    model = LiteLLMModel(client_args={"api_key": s.llm_api_key, "base_url": s.llm_base_url},
                         model_id=f"openai/{_model_id(spec['model'])}")
    mcp_client = MCPClient(lambda: streamablehttp_client(mcp_url))
    mcp_client.__enter__()
    try:
        allowed = set(spec["tools"])
        tools = [t for t in mcp_client.list_tools_sync() if t.tool_name in allowed]
        agent = Agent(model=model, tools=tools, system_prompt=spec["system_prompt"],
                      agent_id=spec["name"])
        return agent, mcp_client
    except Exception:
        mcp_client.__exit__(None, None, None)
        raise


def run_agent(spec_name: str, task: str, mcp_url: str = "http://localhost:8000/mcp") -> str:
    agent, mcp_client = build_agent(spec_name, mcp_url)
    try:
        result = agent(task)
        return str(result)
    finally:
        mcp_client.__exit__(None, None, None)
