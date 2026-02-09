"""Vercel serverless function — proxies AI requests to Anthropic.

Set ANTHROPIC_API_KEY as an environment variable in the Vercel dashboard.
"""

import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
AI_MODEL = "claude-opus-4-6"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self._respond(503, {"error": "API key not configured"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, TypeError):
            body = {}

        prompt = body.get("prompt", "")
        max_tokens = body.get("max_tokens", 300)

        if not prompt:
            self._respond(400, {"error": "prompt is required"})
            return

        payload = json.dumps({
            "model": AI_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(ANTHROPIC_URL, data=payload, headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
            text = data.get("content", [{}])[0].get("text", "No response generated.")
            self._respond(200, {"text": text})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")
            self._respond(502, {"error": f"Anthropic API error: {e.code} {err_body}"})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
