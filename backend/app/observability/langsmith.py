"""LangSmith observability setup and helpers.

Configures LangSmith / LangChain tracing for graph nodes, LLM calls, and
service execution. Environment variables can be provided via .env, runtime
environment, or Cloud Run configuration.
"""

import os
from langsmith import traceable


def configure_langsmith() -> None:
    """Export standard LangSmith / LangChain environment variables."""
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        return

    endpoint = os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT") or "https://api.smith.langchain.com"
    project = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "plum-claims"

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGCHAIN_ENDPOINT"] = endpoint
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGCHAIN_PROJECT"] = project


__all__ = ["configure_langsmith", "traceable"]
