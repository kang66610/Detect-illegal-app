"""Appium explorer engine facade.

The exploration implementation lives in :mod:`agent.ai_explorer.explorer_engine`;
this module keeps the historical import path for workflow assembly and reads
only as the engine appearance: no page keyword rules, no scenario state
machine, no navigation graph, no direct device actions.
"""
from agent.ai_explorer.explorer_engine import AppiumExplorerEngine

__all__ = ["AppiumExplorerEngine"]
