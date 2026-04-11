"""Rickshaw defaults."""
import os

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
MODEL_FAST = os.environ.get("RICKSHAW_FAST", "qwen3.5:4b")
MODEL_THINK = os.environ.get("RICKSHAW_THINK", "qwen3.5:9b")
DEFAULT_MODEL = MODEL_THINK
DB_NAME = "rickshaw.db"
MAX_TOOL_ROUNDS = 8
CONV_HISTORY_LIMIT = 40
MEMORY_INJECT_LIMIT = 20
TEMPERATURE = 0.4
NAME = "Rickshaw"
