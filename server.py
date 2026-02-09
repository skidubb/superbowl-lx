"""Local development server — serves the app and proxies AI requests to Anthropic.

Usage:
    python3 server.py

Requires Python 3.11+ (uses built-in tomllib).
Reads API key from config.toml — copy config.example.toml to get started.
"""

import http.server
import json
import os
import sys
import urllib.request
import urllib.error

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("Python 3.11+ is required (for built-in tomllib). You have Python " + sys.version.split()[0])

PORT = 8080
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
AI_MODEL = "claude-opus-4-6"
ROOT = os.path.dirname(os.path.abspath(__file__))


def load_api_key():
    config_path = os.path.join(ROOT, "config.toml")
    if not os.path.exists(config_path):
        return ""
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    key = config.get("anthropic", {}).get("api_key", "")
    if key == "YOUR_ANTHROPIC_API_KEY_HERE":
        return ""
    return key


API_KEY = load_api_key()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.path = "/superbowl-lx.html"
            return super().do_GET()
        if self.path == "/api/status":
            self._json_response({"ai_enabled": bool(API_KEY)})
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/analyze":
            self._handle_analyze()
            return
        self.send_error(404)

    def _handle_analyze(self):
        if not API_KEY:
            self._json_response({"error": "API key not configured"}, status=503)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        prompt = body.get("prompt", "")
        max_tokens = body.get("max_tokens", 300)

        if not prompt:
            self._json_response({"error": "prompt is required"}, status=400)
            return

        payload = json.dumps({
            "model": AI_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(ANTHROPIC_URL, data=payload, headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        })

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
            text = data.get("content", [{}])[0].get("text", "No response generated.")
            self._json_response({"text": text})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")
            self._json_response({"error": f"Anthropic API error: {e.code} {err_body}"}, status=502)
        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def _json_response(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Quieter logging — just method + path
        sys.stderr.write(f"  {args[0]}\n")


if __name__ == "__main__":
    ai_status = "enabled" if API_KEY else "disabled (set key in config.toml)"
    print(f"Serving at http://localhost:{PORT} — AI: {ai_status}")
    server = http.server.HTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
