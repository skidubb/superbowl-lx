"""Vercel serverless function — proxies AI requests to Anthropic.

Set ANTHROPIC_API_KEY as an environment variable in the Vercel dashboard.
"""

import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
AI_MODEL = "claude-opus-4-6"

MAX_REQUESTS_PER_HOUR = 10
CACHE_TTL = 3600  # 1 hour

RATE_LIMIT_PATH = "/tmp/rate_limits.json"
RESPONSE_CACHE_PATH = "/tmp/response_cache.json"


def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _check_rate_limit(ip):
    limits = _load_json(RATE_LIMIT_PATH)
    now = time.time()
    record = limits.get(ip, {"count": 0, "window_start": now})
    if now - record["window_start"] > 3600:
        record = {"count": 0, "window_start": now}
    if record["count"] >= MAX_REQUESTS_PER_HOUR:
        return False
    record["count"] += 1
    limits[ip] = record
    # Evict expired entries
    limits = {k: v for k, v in limits.items() if now - v["window_start"] <= 3600}
    _save_json(RATE_LIMIT_PATH, limits)
    return True


def _get_cached(prompt_hash):
    cache = _load_json(RESPONSE_CACHE_PATH)
    entry = cache.get(prompt_hash)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["text"]
    return None


def _set_cached(prompt_hash, text):
    cache = _load_json(RESPONSE_CACHE_PATH)
    now = time.time()
    cache[prompt_hash] = {"text": text, "ts": now}
    # Evict expired entries
    cache = {k: v for k, v in cache.items() if now - v["ts"] < CACHE_TTL}
    _save_json(RESPONSE_CACHE_PATH, cache)


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

        # Check response cache (cached responses are free — skip rate limit)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        cached = _get_cached(prompt_hash)
        if cached:
            self._respond(200, {"text": cached})
            return

        # Rate limit only uncached requests (these hit the Anthropic API)
        ip = (self.headers.get("X-Forwarded-For") or "unknown").split(",")[0].strip()
        if not _check_rate_limit(ip):
            self._respond(429, {"error": "Rate limit exceeded. Try again later."})
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
            _set_cached(prompt_hash, text)
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
