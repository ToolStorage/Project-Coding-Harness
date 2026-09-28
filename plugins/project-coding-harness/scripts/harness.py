"""Local CLI, MCP stdio server, and loopback dashboard for Project Coding Harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from store import ACTIONS, Store, dispatch

UI = Path(__file__).resolve().parent.parent / "ui" / "dashboard.html"
URI = "ui://project-coding-harness/dashboard-v1.html"
DESCRIPTIONS = {
    "preferences": "Read only project usage settings and whether analysis exists; no memory contents or source scan. For substantive coding activation checks, not trivial tasks. A conversation-only opt-out needs no tool call or persistent setting.",
    "status": "Read project memory, settings, pending user requests and proposals. project_root must be the user's actual project, never the plugin installation directory.",
    "dashboard": "Show project controls and return a loopback browser fallback URL. No analysis is performed by opening it.",
    "configure": "Save explicitly requested project settings from conversation or UI. Partial payload: usage_mode (auto|on_request), offer_setup (boolean), review_depth (standard|deep), max_rounds (integer 1..10). Omitted fields remain unchanged. Do not save conversation-only opt-outs. Does not analyze the project.",
    "request_analysis": "ONLY when user explicitly requests analysis/refresh. payload: mode (analyze|refresh). Creates a request; model must inspect actual source then save_analysis. No analysis is done by this tool.",
    "save_analysis": "Commit analysis for pending request. payload: request_id, name, project, architecture, verification (Markdown), evidence (relative paths), note_decisions (every note ID -> action keep|update|archive|uncertain, reason, evidence for keep/update, body for update). Read skill memory reference first.",
    "cancel_request": "Cancel a pending analysis request on user request or when its revision is stale. payload: request_id.",
    "propose": "Stage a useful long-term memory, NOT active memory. payload: title, body (Markdown), evidence (relative paths). Ask user '<title>을 메모리에 기억해둘까요?' after finishing their work. Do not accept your own proposal.",
    "decide_proposal": "ONLY after explicit user decision. payload: proposal_id, decision accept|decline, user_confirmed true. Silence, elapsed time, or another task is not consent.",
    "start_review": "Start bounded review bookkeeping for a coding change; payload: scope. Freezes project settings for this run. Does not invoke a model or run tests.",
    "record_review": "Record actual review evidence. payload: run_id, round (sequential, starts 1), review_complete bool, verification_passed bool, unresolved_issues integer, evidence (commands/results/findings, reviewed code state). Stops on clean verified review, incomplete review, or cap. Does not execute review itself.",
}


def tools_list():
    tools = []
    for name, description in DESCRIPTIONS.items():
        tool = {"name": "harness_" + name, "description": description,
                "inputSchema": {"type": "object", "properties": {"project_root": {"type": "string"}, "payload": {"type": "object"}},
                                "required": ["project_root"], "additionalProperties": False},
                "annotations": {"readOnlyHint": name in ("status", "preferences"), "destructiveHint": False, "openWorldHint": False}}
        if name == "dashboard":
            tool["_meta"] = {"ui": {"resourceUri": URI}, "openai/outputTemplate": URI}
        tools.append(tool)
    return tools


class Dashboard:
    """One project per random-token URL. Never accepts arbitrary project roots from HTTP."""
    def __init__(self, root):
        self.root = str(Store(root).root)
        self.token = secrets.token_urlsafe(32)
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, body, mime="application/json; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)

            def valid(self):
                expected = f"127.0.0.1:{dashboard.server.server_port}"
                return self.headers.get("Host") == expected and urlsplit(self.path).path.startswith("/" + dashboard.token + "/")

            def do_GET(self):
                if not self.valid():
                    return self.reply(403, '{"error":"Forbidden"}')
                route = urlsplit(self.path).path.split("/")[-1]
                if route == "":
                    return self.reply(200, UI.read_text(encoding="utf-8"), "text/html; charset=utf-8")
                if route == "status":
                    try:
                        return self.reply(200, json.dumps(Store(dashboard.root).status(), ensure_ascii=False))
                    except Exception as exc:
                        return self.reply(400, json.dumps({"error": str(exc)}))
                self.reply(404, '{"error":"Not found"}')

            def do_POST(self):
                origin = f"http://127.0.0.1:{dashboard.server.server_port}"
                if not self.valid() or self.headers.get("Origin") != origin or self.headers.get("Content-Type") != "application/json":
                    return self.reply(403, '{"error":"Forbidden"}')
                action = urlsplit(self.path).path.split("/")[-1]
                # Browser cannot directly commit model analysis or fabricate review results.
                if action not in ("configure", "request_analysis", "cancel_request", "decide_proposal"):
                    return self.reply(403, '{"error":"Action not available in browser"}')
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        raise ValueError("Invalid request length")
                    payload = json.loads(self.rfile.read(length))
                    self.reply(200, json.dumps(dispatch(action, dashboard.root, payload), ensure_ascii=False))
                except Exception as exc:
                    self.reply(400, json.dumps({"error": str(exc)}, ensure_ascii=False))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/{self.token}/"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class MCP:
    def __init__(self):
        self.dashboards = {}

    def handle(self, request):
        method, params = request.get("method"), request.get("params", {})
        if method == "initialize":
            supported = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
            version = params.get("protocolVersion")
            return {"protocolVersion": version if version in supported else "2025-11-25",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "project-coding-harness", "version": "0.1.0"},
                    "instructions": "Read project-coding-harness skill. The model does analysis/review; tools persist evidence and UI settings. Never accept a memory proposal without explicit user consent."}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": tools_list()}
        if method == "resources/list":
            return {"resources": [{"uri": URI, "name": "Harness controls", "mimeType": "text/html;profile=mcp-app"}]}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        if method == "resources/read":
            if params.get("uri") != URI:
                raise ValueError("Unknown resource")
            return {"contents": [{"uri": URI, "mimeType": "text/html;profile=mcp-app", "text": UI.read_text(encoding="utf-8"),
                                   "_meta": {"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}}}]}
        if method == "tools/call":
            try:
                name = params.get("name", "")
                if not name.startswith("harness_") or name[8:] not in DESCRIPTIONS:
                    raise ValueError("Unknown tool")
                args = params.get("arguments", {})
                action, root = name[8:], args["project_root"]
                if action == "dashboard":
                    root = str(Store(root).root)
                    if root not in self.dashboards:
                        self.dashboards[root] = Dashboard(root)
                    result = Store(root).status()
                    result["dashboard_url"] = self.dashboards[root].url
                else:
                    result = dispatch(action, root, args.get("payload", {}))
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result}
            except Exception as exc:
                return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        raise ValueError("Method not found")

    def serve(self):
        for line in sys.stdin:
            request = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Invalid request")
                if "id" not in request:
                    continue
                result = self.handle(request)
                response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                            "error": {"code": -32603, "message": str(exc)}}
            print(json.dumps(response, ensure_ascii=False), flush=True)
        for dashboard in self.dashboards.values():
            dashboard.close()


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("mcp", "dashboard", "call"))
    parser.add_argument("action", nargs="?", choices=ACTIONS)
    parser.add_argument("--project")
    parser.add_argument("--payload", help="UTF-8 JSON file; use - for stdin")
    args = parser.parse_args()
    if args.project:
        bound = Path(args.project).expanduser()
        if not bound.is_absolute() or not bound.is_dir():
            parser.error("--project must be an existing absolute directory")
        Store.allowed_root = bound.resolve()
    if args.command == "mcp":
        return MCP().serve()
    if not args.project:
        parser.error("--project is required")
    if args.command == "dashboard":
        dashboard = Dashboard(args.project)
        print(dashboard.url, flush=True)
        try:
            dashboard.thread.join()
        except KeyboardInterrupt:
            dashboard.close()
    else:
        if not args.action:
            parser.error("call requires an action")
        payload = json.loads(sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text(encoding="utf-8-sig")) if args.payload else {}
        print(json.dumps(dispatch(args.action, args.project, payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
