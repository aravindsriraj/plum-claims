"""Shared test configuration.

Disable the member-message polish pass for the whole suite: it is an LLM
prose rewrite, and tests must stay deterministic and LLM-free. Production
leaves it enabled (default true in app.main).
"""

import os

os.environ["CLAIMS_POLISH_MESSAGES"] = "false"
os.environ["CLAIMS_HITL"] = "false"
