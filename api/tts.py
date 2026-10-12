from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import asyncio
import tempfile
import os

import aiohttp
import edge_tts

VOICE = "en-US-JennyNeural"  # pick any valid Edge voice
# Microsoft may reject datacenter IPs (e.g. Vercel/AWS) with a 403; route through
# a residential/other proxy by setting EDGE_TTS_PROXY, e.g. http://user:pass@host:port
PROXY = os.environ.get("EDGE_TTS_PROXY") or None
MAX_ATTEMPTS = 3


async def synth_to_bytes(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                communicate = edge_tts.Communicate(text, VOICE, proxy=PROXY)
                await communicate.save(tmp_path)
                break
            except aiohttp.WSServerHandshakeError as e:
                if e.status != 403 or attempt == MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(attempt)
        with open(tmp_path, "rb") as f:
            audio = f.read()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return audio


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Read ?text=... from the query string
        query = parse_qs(urlparse(self.path).query)
        text = query.get("text", ["Hello from edge-tts on Vercel"])[0]

        try:
            audio = asyncio.run(synth_to_bytes(text))
        except Exception as e:
            body = f"TTS failed: {e!r}".encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        # Optional CORS if you call this from another origin
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(audio)
