"""Rickshaw Engine — Agent loop with native tool calling."""
import json
import os
import time
from datetime import datetime, timezone

from . import config
from .context import ContextLoader
from .tools import BUILTIN_TOOLS, ToolExecutor


class Engine:
    def __init__(self, brain, backend, mcp_bridge=None, cwd=None):
        self.brain = brain
        self.backend = backend
        self.mcp = mcp_bridge
        self.tool_exec = ToolExecutor(brain)
        self.context = ContextLoader(cwd=cwd)
        self.session_id = "default"
        self.on_tool_call = None   # callback(tool_name, args, result)
        self.on_thinking = None    # callback(text)

    def _all_tools(self):
        """Combine built-in tools + MCP tools."""
        tools = list(BUILTIN_TOOLS)
        if self.mcp:
            tools.extend(self.mcp.get_tools())
        return tools

    def _system_prompt(self):
        name = self.brain.get_config("name", config.NAME)
        persona = self.brain.get_config(
            "personality",
            "A capable local AI agent. You are fast, precise, and tool-savvy. "
            "Use tools proactively — don't guess when you can look up. "
            "Be concise. No filler."
        )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        local_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        parts = [
            f"You are {name}. {persona}",
            f"\nCurrent time: {local_now} (UTC: {now})",
        ]

        # Inject long-term memories
        memories = self.brain.get_memories(limit=config.MEMORY_INJECT_LIMIT)
        if memories:
            parts.append("\n## Your Memories")
            for m in memories:
                parts.append(f"- [{m['category']}] {m['content']}")

        # Inject session recap if resuming
        last = self.brain.get_last_session()
        if last and last.get("summary"):
            parts.append(f"\n## Last Session Recap\n{last['summary']}")
            if last.get("next_steps"):
                parts.append("Next steps: " + ", ".join(last["next_steps"]))

        parts.append(
            "\n## Rules\n"
            "- Use tools to take action. Don't describe what you would do -- do it.\n"
            "- Use remember/recall for anything the user wants persisted.\n"
            "- Be direct. Answer first, explain only if asked.\n"
            "- If a tool errors, report the error concisely.\n"
            "- Never fabricate tool results."
        )

        # Inject RICKSHAW.md context (like Claude's CLAUDE.md)
        ctx_block = self.context.build_context_block()
        if ctx_block:
            parts.append(f"\n{ctx_block}")

        return "\n".join(parts)

    def _execute_tool(self, name, args):
        """Route tool call to built-in executor or MCP bridge."""
        if self.mcp and self.mcp.has_tool(name):
            return self.mcp.call_tool(name, args)
        return self.tool_exec.execute(name, args)

    def process(self, user_text, model=None):
        """Process user input through the agent loop. Returns response text."""
        self.brain.add_message("user", user_text, self.session_id)

        # Build message history
        messages = [{"role": "system", "content": self._system_prompt()}]
        for m in self.brain.get_messages(self.session_id, limit=config.CONV_HISTORY_LIMIT):
            msg = {"role": m["role"], "content": m["content"]}
            if m.get("tool_calls"):
                msg["tool_calls"] = m["tool_calls"]
            if m.get("tool_call_id"):
                msg["tool_call_id"] = m["tool_call_id"]
            messages.append(msg)

        all_tools = self._all_tools()

        # Agent loop — max rounds
        for round_num in range(config.MAX_TOOL_ROUNDS):
            try:
                result = self.backend.chat(
                    messages, tools=all_tools if all_tools else None,
                    model=model,
                )
            except Exception as e:
                error = f"Backend error: {e}"
                self.brain.add_message("assistant", error, self.session_id)
                return error

            content = result.get("content", "")
            tool_calls = result.get("tool_calls")

            # No tool calls — we're done
            if not tool_calls:
                if content:
                    self.brain.add_message("assistant", content, self.session_id)
                return content or "(empty response)"

            # Store assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })
            self.brain.add_message(
                "assistant", content, self.session_id,
                tool_calls=tool_calls,
            )

            # Execute each tool call
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "unknown")
                raw_args = fn.get("arguments", "{}")
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                tc_id = tc.get("id", f"call_{round_num}")

                t0 = time.time()
                try:
                    tool_result = str(self._execute_tool(tool_name, args))
                    elapsed = int((time.time() - t0) * 1000)
                    status = "success"
                    error = None
                except Exception as e:
                    elapsed = int((time.time() - t0) * 1000)
                    tool_result = f"Tool error: {e}"
                    status = "error"
                    error = str(e)

                # Log
                self.brain.add_tool_call(
                    self.session_id, tool_name,
                    raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
                    tool_result, status, error, elapsed,
                )

                # Callback
                if self.on_tool_call:
                    self.on_tool_call(tool_name, args, tool_result, elapsed)

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result[:4000],
                })
                self.brain.add_message(
                    "tool", tool_result[:4000], self.session_id,
                    tool_call_id=tc_id,
                )

        return content if content else "(max tool rounds reached)"

    def save_session(self, summary=None):
        """Save current session state for resume."""
        if not summary:
            # Auto-generate from recent messages
            recent = self.brain.get_messages(self.session_id, limit=6)
            parts = []
            for m in recent:
                if m["role"] in ("user", "assistant") and m["content"]:
                    parts.append(f"{m['role']}: {m['content'][:200]}")
            summary = "Recent conversation:\n" + "\n".join(parts) if parts else "Empty session."

        self.brain.save_session(
            self.session_id, summary,
            model=self.backend.model,
        )
        return summary

    def tool_count(self):
        n = len(BUILTIN_TOOLS)
        if self.mcp:
            n += self.mcp.tool_count()
        return n
