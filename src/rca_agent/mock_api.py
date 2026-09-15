"""A standalone synthetic HTTP service; the agent accesses it only through HTTP."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def handler_for(data_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urlparse(self.path)
            status, content = 200, b""
            if query.path == "/health":
                content = json.dumps({"status": "ok", "source": "synthetic mock HTTP API"}).encode()
            elif query.path == "/events":
                fault = parse_qs(query.query).get("fault", [None])[0]
                if fault == "unavailable":
                    status, content = 503, b'{"error":"simulated outage"}'
                elif fault == "malformed":
                    content = b'{"events": invalid json'
                else:
                    try:
                        content = (data_dir / "api-events.json").read_bytes()
                    except OSError:
                        status, content = 503, b'{"error":"Run rca seed first"}'
            else:
                status, content = 404, b'{"error":"not found"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    return Handler


@contextmanager
def running_mock(data_dir: Path, port: int = 0):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(data_dir))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/events"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def serve_mock(data_dir: Path, port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(data_dir))
    print(f"Synthetic mock API: http://127.0.0.1:{port}/events", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
