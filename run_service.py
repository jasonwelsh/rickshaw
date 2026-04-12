"""Rickshaw Service — Run the Telegram bot as a background service.

Usage:
    pythonw run_service.py              (background, no window)
    python run_service.py               (foreground for debugging)
    python run_service.py --fast        (use 4B model)
    python run_service.py --model X     (use specific model)

Rickshaw listens on @rickshaw_ai_bot, processes messages through
Qwen 3.5 with tool calling, and responds on Telegram.
"""
import argparse
import logging
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

LOG_FILE = os.path.join(SCRIPT_DIR, "rickshaw_service.log")
PID_FILE = os.path.join(SCRIPT_DIR, "rickshaw.pid")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("rickshaw")


def main():
    parser = argparse.ArgumentParser(description="Rickshaw Service")
    parser.add_argument("--model", default=None)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--mcp", default=None)
    args = parser.parse_args()

    from rickshaw import config
    from rickshaw.brain import Brain
    from rickshaw.backend import Backend
    from rickshaw.engine import Engine
    from rickshaw.mcp_bridge import MCPBridge
    from rickshaw.telegram import TelegramBot

    model = config.MODEL_FAST if args.fast else (args.model or config.DEFAULT_MODEL)

    # Init
    brain = Brain(os.path.join(SCRIPT_DIR, config.DB_NAME))
    backend = Backend(model=model)

    # MCP bridge
    mcp = None
    mcp_path = args.mcp or os.path.join(SCRIPT_DIR, "mcp_servers.json")
    if os.path.exists(mcp_path):
        try:
            mcp = MCPBridge(mcp_path)
            if mcp.tool_count() > 0:
                log.info(f"MCP: {mcp.tool_count()} tools loaded")
        except Exception as e:
            log.warning(f"MCP load failed: {e}")

    engine = Engine(brain, backend, mcp, cwd=SCRIPT_DIR)

    # Check Ollama
    if not backend.ping():
        log.error(f"Ollama not reachable at {backend.base_url}")
        sys.exit(1)

    # Start bot
    bot = TelegramBot(brain, engine, backend)
    if not bot.token:
        log.error("No bot token configured in rickshaw.db")
        sys.exit(1)

    # Tool call logging
    def on_tool(name, args, result, elapsed):
        log.info(f"[tool] {name}({args}) -> {elapsed}ms")
    engine.on_tool_call = on_tool

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log.info(f"Rickshaw service starting")
    log.info(f"  Model:  {model}")
    log.info(f"  Tools:  {engine.tool_count()}")
    log.info(f"  Bot:    {bot.token[:10]}...")

    if not bot.start():
        log.error("Bot failed to start")
        sys.exit(1)

    log.info("Telegram bot polling started")

    # Keep alive
    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        bot.stop()
        if mcp:
            mcp.shutdown()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


if __name__ == "__main__":
    main()
