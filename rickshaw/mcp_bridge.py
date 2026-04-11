"""Rickshaw MCP Bridge — Spawn and communicate with MCP servers over stdio."""
import json
import os
import subprocess
import threading


class MCPServer:
    """Manages a single MCP server subprocess."""

    def __init__(self, name, command, args=None, env=None):
        self.name = name
        self.tools = []
        self._id = 0
        self._lock = threading.Lock()

        full_env = {**os.environ, **(env or {})}
        self.process = subprocess.Popen(
            [command] + (args or []),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
        )
        self._initialize()
        self.tools = self._list_tools()

    def _next_id(self):
        self._id += 1
        return self._id

    def _write(self, msg):
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self.process.stdin.write(header + body)
        self.process.stdin.flush()

    def _read(self):
        """Read one JSON-RPC message from stdout."""
        # Read headers
        content_length = 0
        while True:
            line = self.process.stdout.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
            decoded = line.decode("utf-8").strip()
            if decoded.lower().startswith("content-length:"):
                content_length = int(decoded.split(":", 1)[1].strip())

        if content_length == 0:
            return None
        body = self.process.stdout.read(content_length)
        return json.loads(body.decode("utf-8"))

    def _request(self, method, params=None):
        """Send a JSON-RPC request and wait for the matching response."""
        with self._lock:
            rid = self._next_id()
            msg = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                msg["params"] = params
            self._write(msg)

            # Read until we get our response (skip notifications)
            while True:
                resp = self._read()
                if resp is None:
                    return None
                if resp.get("id") == rid:
                    return resp
                # else: notification — discard

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def _initialize(self):
        resp = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "rickshaw", "version": "0.1.0"},
        })
        self._notify("notifications/initialized")
        return resp

    def _list_tools(self):
        resp = self._request("tools/list")
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def call_tool(self, name, arguments):
        """Call a tool by name. Returns the result content."""
        resp = self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        if resp is None:
            return "MCP server did not respond."
        if "error" in resp:
            return f"MCP error: {resp['error'].get('message', str(resp['error']))}"
        result = resp.get("result", {})
        # Extract text from content array
        content_parts = result.get("content", [])
        texts = []
        for part in content_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part["text"])
            elif isinstance(part, str):
                texts.append(part)
        return "\n".join(texts) if texts else json.dumps(result)

    def shutdown(self):
        try:
            self._notify("notifications/cancelled", {"reason": "shutdown"})
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()


class MCPBridge:
    """Manages multiple MCP servers and provides unified tool access."""

    def __init__(self, config_path=None):
        self.servers = {}          # name -> MCPServer
        self.tool_map = {}         # tool_name -> server_name
        self.tool_schemas = []     # OpenAI-format tool defs
        if config_path and os.path.exists(config_path):
            self._load_config(config_path)

    def _load_config(self, path):
        with open(path, "r") as f:
            config = json.load(f)

        for name, spec in config.get("mcpServers", {}).items():
            cmd = spec.get("command", "python")
            args = spec.get("args", [])
            env = spec.get("env")
            try:
                self.add_server(name, cmd, args, env)
            except Exception as e:
                print(f"  [mcp] Failed to start {name}: {e}")

    def add_server(self, name, command, args=None, env=None):
        server = MCPServer(name, command, args, env)
        self.servers[name] = server

        for tool in server.tools:
            tool_name = tool["name"]
            self.tool_map[tool_name] = name
            # Convert MCP schema to OpenAI function format
            self.tool_schemas.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {
                        "type": "object", "properties": {}
                    }),
                },
            })

        return len(server.tools)

    def get_tools(self):
        """Return all MCP tool schemas in OpenAI format."""
        return self.tool_schemas

    def has_tool(self, name):
        return name in self.tool_map

    def call_tool(self, name, arguments):
        server_name = self.tool_map.get(name)
        if not server_name:
            return f"Unknown MCP tool: {name}"
        server = self.servers.get(server_name)
        if not server:
            return f"MCP server {server_name} not running."
        return server.call_tool(name, arguments)

    def tool_count(self):
        return len(self.tool_map)

    def list_tools(self):
        """Return list of (tool_name, server_name, description)."""
        result = []
        for schema in self.tool_schemas:
            fn = schema["function"]
            server = self.tool_map.get(fn["name"], "?")
            result.append((fn["name"], server, fn.get("description", "")[:80]))
        return result

    def shutdown(self):
        for server in self.servers.values():
            server.shutdown()
        self.servers.clear()
        self.tool_map.clear()
        self.tool_schemas.clear()
