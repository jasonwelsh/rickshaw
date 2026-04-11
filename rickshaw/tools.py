"""Rickshaw Tools — Built-in tool definitions and registry."""
import json
import os
import subprocess
import platform
from datetime import datetime, timezone


# ── Tool Schema Definitions ─────────────────────────────────────────

BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Save a fact, preference, decision, or note to persistent memory. Use this whenever the user says to remember something or when you learn important context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "What to remember"},
                    "category": {
                        "type": "string",
                        "enum": ["fact", "preference", "decision", "note", "task"],
                        "description": "Memory category",
                    },
                },
                "required": ["content", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Search persistent memories. Use when the user asks 'do you remember', 'what did I say about', or when you need context from past sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term (optional)"},
                    "category": {"type": "string", "description": "Filter by category (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Delete a specific memory by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "integer", "description": "Memory ID to delete"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return its output. Use for system tasks, file operations, git commands, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "working_dir": {"type": "string", "description": "Working directory (optional)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "max_lines": {"type": "integer", "description": "Max lines to return (default 200)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "pattern": {"type": "string", "description": "Glob pattern filter (e.g. '*.py')"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ── Tool Handlers ────────────────────────────────────────────────────

class ToolExecutor:
    """Executes built-in tools. MCP tools are handled by MCPBridge."""

    def __init__(self, brain):
        self.brain = brain

    def execute(self, name, args):
        handler = getattr(self, f"_tool_{name}", None)
        if handler:
            return handler(args)
        return f"Unknown built-in tool: {name}"

    def _tool_remember(self, args):
        content = args.get("content", "")
        category = args.get("category", "note")
        mid = self.brain.add_memory(category, content)
        return f"Saved memory #{mid} [{category}]: {content[:100]}"

    def _tool_recall(self, args):
        query = args.get("query")
        category = args.get("category")
        memories = self.brain.get_memories(category=category, query=query, limit=10)
        if not memories:
            return "No memories found."
        lines = []
        for m in memories:
            lines.append(f"#{m['id']} [{m['category']}] {m['content']}")
        return "\n".join(lines)

    def _tool_forget(self, args):
        mid = args.get("memory_id")
        self.brain.delete_memory(mid)
        return f"Deleted memory #{mid}"

    def _tool_run_command(self, args):
        cmd = args.get("command", "")
        cwd = args.get("working_dir")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=30, cwd=cwd,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\n(exit code {result.returncode})"
            return output[:4000] or "(no output)"
        except subprocess.TimeoutExpired:
            return "Command timed out after 30 seconds."
        except Exception as e:
            return f"Error: {e}"

    def _tool_read_file(self, args):
        path = args.get("path", "")
        max_lines = args.get("max_lines", 200)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
            return "".join(lines) or "(empty file)"
        except Exception as e:
            return f"Error reading {path}: {e}"

    def _tool_write_file(self, args):
        path = args.get("path", "")
        content = args.get("content", "")
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"

    def _tool_list_files(self, args):
        import glob as globmod
        path = args.get("path", ".")
        pattern = args.get("pattern", "*")
        try:
            full_pattern = os.path.join(path, pattern)
            files = globmod.glob(full_pattern)
            if not files:
                return f"No files matching {pattern} in {path}"
            entries = []
            for f in sorted(files)[:50]:
                kind = "dir" if os.path.isdir(f) else "file"
                size = os.path.getsize(f) if os.path.isfile(f) else 0
                entries.append(f"{kind:4s} {size:>10,d}  {os.path.basename(f)}")
            return "\n".join(entries)
        except Exception as e:
            return f"Error: {e}"

    def _tool_get_time(self, _args):
        now = datetime.now(timezone.utc)
        local = datetime.now()
        return f"UTC: {now.strftime('%Y-%m-%d %H:%M:%S')}\nLocal: {local.strftime('%Y-%m-%d %H:%M:%S')}"
