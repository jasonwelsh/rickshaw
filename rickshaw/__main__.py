"""Rickshaw — Interactive CLI agent."""
import argparse
import os
import sys
import signal

from . import __version__, config
from .brain import Brain
from .backend import Backend
from .engine import Engine
from .mcp_bridge import MCPBridge


# ── ANSI colors ──────────────────────────────────────────────────────
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def tool_callback(name, args, result, elapsed):
    arg_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items()) if args else ""
    print(f"  {DIM}[tool] {name}({arg_str}) -> {elapsed}ms{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Rickshaw — Local LLM Agent")
    parser.add_argument("--model", default=None, help=f"Model (default: {config.DEFAULT_MODEL})")
    parser.add_argument("--fast", action="store_true", help=f"Use fast model ({config.MODEL_FAST})")
    parser.add_argument("--url", default=None, help=f"Ollama URL (default: {config.OLLAMA_URL})")
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--mcp", default=None, help="MCP servers config JSON path")
    parser.add_argument("--name", default=None, help="Agent name")
    parser.add_argument("prompt", nargs="*", help="One-shot prompt (skips REPL)")
    args = parser.parse_args()

    # Resolve paths
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = args.db or os.path.join(project_dir, config.DB_NAME)
    mcp_path = args.mcp or os.path.join(project_dir, "mcp_servers.json")

    model = config.MODEL_FAST if args.fast else (args.model or config.DEFAULT_MODEL)

    # Init components
    brain = Brain(db_path)
    if args.name:
        brain.set_config("name", args.name)

    backend = Backend(base_url=args.url, model=model)

    # MCP bridge (optional)
    mcp = None
    mcp_config = mcp_path if os.path.exists(mcp_path) else None
    if mcp_config:
        print(f"{DIM}Loading MCP servers...{RESET}")
        mcp = MCPBridge(mcp_config)
        if mcp.tool_count() > 0:
            print(f"{DIM}  {mcp.tool_count()} MCP tools loaded{RESET}")

    engine = Engine(brain, backend, mcp)
    engine.on_tool_call = tool_callback

    # Check backend
    if not backend.ping():
        print(f"{YELLOW}Warning: Ollama not reachable at {backend.base_url}{RESET}")
        print(f"{DIM}Start Ollama or set --url{RESET}")

    name = brain.get_config("name", config.NAME)

    # One-shot mode
    if args.prompt:
        prompt = " ".join(args.prompt)
        response = engine.process(prompt)
        print(response)
        if mcp:
            mcp.shutdown()
        return

    # Interactive REPL
    print(f"{BOLD}{name}{RESET} v{__version__} | {CYAN}{model}{RESET} | {engine.tool_count()} tools")
    print(f"{DIM}Type /help for commands, /quit to exit{RESET}")
    print()

    def handle_sigint(sig, frame):
        print(f"\n{DIM}Use /quit to exit{RESET}")

    signal.signal(signal.SIGINT, handle_sigint)

    while True:
        try:
            user_input = input(f"{GREEN}> {RESET}").strip()
        except EOFError:
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            cmd = user_input.lower().split()
            handled = handle_command(cmd, engine, brain, backend, mcp)
            if handled == "quit":
                break
            continue

        # Process through engine
        response = engine.process(user_input)
        print(f"\n{response}\n")

    # Cleanup
    print(f"\n{DIM}Saving session...{RESET}")
    engine.save_session()
    if mcp:
        mcp.shutdown()
    print(f"{DIM}Goodbye.{RESET}")


def handle_command(cmd, engine, brain, backend, mcp):
    name = cmd[0]

    if name in ("/quit", "/exit", "/q"):
        return "quit"

    elif name == "/help":
        print(f"""
{BOLD}Commands:{RESET}
  /model <name>     Switch model (e.g. /model qwen3.5:4b)
  /fast             Switch to fast model ({config.MODEL_FAST})
  /think            Switch to think model ({config.MODEL_THINK})
  /tools            List all available tools
  /memory           Show all memories
  /stats            Show session stats
  /reset            Clear conversation history
  /save [summary]   Save session for later resume
  /resume           Load last session recap
  /quit             Exit
""")

    elif name == "/model" and len(cmd) > 1:
        backend.model = cmd[1]
        print(f"{DIM}Model → {cmd[1]}{RESET}")

    elif name == "/fast":
        backend.model = config.MODEL_FAST
        print(f"{DIM}Model → {config.MODEL_FAST}{RESET}")

    elif name == "/think":
        backend.model = config.MODEL_THINK
        print(f"{DIM}Model → {config.MODEL_THINK}{RESET}")

    elif name == "/tools":
        print(f"\n{BOLD}Built-in tools:{RESET}")
        from .tools import BUILTIN_TOOLS
        for t in BUILTIN_TOOLS:
            fn = t["function"]
            print(f"  {fn['name']:20s} {fn['description'][:60]}")
        if mcp and mcp.tool_count() > 0:
            print(f"\n{BOLD}MCP tools:{RESET}")
            for tname, server, desc in mcp.list_tools():
                print(f"  {tname:20s} [{server}] {desc}")
        print(f"\n{DIM}Total: {engine.tool_count()} tools{RESET}")

    elif name == "/memory":
        memories = brain.get_memories(limit=30)
        if not memories:
            print(f"{DIM}No memories saved yet.{RESET}")
        else:
            for m in memories:
                print(f"  #{m['id']} [{m['category']}] {m['content'][:80]}")

    elif name == "/stats":
        s = brain.stats()
        print(f"  Messages:   {s['messages']}")
        print(f"  Memories:   {s['memories']}")
        print(f"  Tool calls: {s['tool_calls']} ({s['tool_calls_ok']} ok, {s['tool_calls_err']} err)")
        print(f"  Model:      {backend.model}")

    elif name == "/reset":
        brain.clear_messages(engine.session_id)
        print(f"{DIM}Conversation cleared.{RESET}")

    elif name == "/save":
        summary = " ".join(cmd[1:]) if len(cmd) > 1 else None
        saved = engine.save_session(summary)
        print(f"{DIM}Session saved.{RESET}")

    elif name == "/resume":
        last = brain.get_last_session()
        if last:
            print(f"\n{BOLD}Last session{RESET} ({last.get('ended', '?')}):")
            print(f"  {last['summary']}")
            if last.get("next_steps"):
                print(f"  Next: {', '.join(last['next_steps'])}")
        else:
            print(f"{DIM}No previous session found.{RESET}")

    else:
        print(f"{DIM}Unknown command. Type /help{RESET}")

    return None


if __name__ == "__main__":
    main()
