from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import asyncio
import tempfile
import os

import edge_tts


async def synth_to_bytes(text: str) -> bytes:
    voice = "en-US-JennyNeural"  # pick any valid Edge voice
    communicate = edge_tts.Communicate(text, voice)

    # Save to a temp file, then read bytes back
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    try:
        await communicate.save(tmp_path)
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

        # Run the async TTS code
        audio = asyncio.run(synth_to_bytes(text))

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        # Optional CORS if you call this from another origin
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(audio)
