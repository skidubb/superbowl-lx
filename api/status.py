"""Vercel serverless function — reports whether AI is available."""

import json
import os
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ai_enabled = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
        body = json.dumps({"ai_enabled": ai_enabled}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
