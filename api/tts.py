from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import asyncio
import os
import threading

import aiohttp
import edge_tts


DEFAULT_TEXT = "Hello from edge-tts on Vercel"
DEFAULT_VOICE = "ar-AE-HamdanNeural"

# Microsoft rejects some datacenter IPs (e.g. Vercel/AWS) with a 403; route through
# a residential proxy by setting EDGE_TTS_PROXY, e.g. http://user:pass@host:port
PROXY = os.environ.get("EDGE_TTS_PROXY") or None
MAX_ATTEMPTS = 3


async def synth_to_bytes(text: str, voice: str) -> bytes:
    """
    Synthesize speech and return MP3 bytes (no temp files).
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            communicate = edge_tts.Communicate(text, voice, proxy=PROXY)

            audio = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    audio.extend(chunk["data"])

            return bytes(audio)
        except aiohttp.WSServerHandshakeError as e:
            if e.status != 403 or attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(attempt)


def run_coro(coro):
    """
    Run an async coroutine safely.

    In normal http.server usage there is no running loop, so asyncio.run() works.
    This helper also handles the edge case where an event loop is already running.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # If there's already a running loop in this thread, run the coroutine in a new thread/loop.
    result = {"value": None, "error": None}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result["value"] = loop.run_until_complete(coro)
        except Exception as e:
            result["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()

    if result["error"] is not None:
        raise result["error"]
    return result["value"]


class handler(BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        try:
            # Parse query string
            query = parse_qs(urlparse(self.path).query, keep_blank_values=True)

            # Text param (default if missing)
            text = (query.get("text", [DEFAULT_TEXT])[0] or DEFAULT_TEXT).strip()

            # Voice param (default if missing/empty)
            voice = (query.get("voice", [DEFAULT_VOICE])[0] or DEFAULT_VOICE).strip()

            # (Optional) basic guard to prevent huge inputs
            max_chars = 8000
            if len(text) > max_chars:
                raise ValueError(f"text is too long ({len(text)} chars). Max is {max_chars}.")

            audio = run_coro(synth_to_bytes(text, voice))

            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self._send_cors()
            self.end_headers()
            self.wfile.write(audio)

        except Exception as e:
            err_msg = f"Error in tts function: {type(e).__name__}: {e}"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self._send_cors()
            self.end_headers()
            self.wfile.write(err_msg.encode("utf-8"))
