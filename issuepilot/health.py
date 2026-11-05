import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def handler_type(status, stale_after):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/healthz", "/readyz"):
                self.send_error(404)
                return
            snapshot = dict(status)
            ready = bool(snapshot.get("last_poll_ok")) and time.time() - snapshot.get("last_cycle", 0) < stale_after
            payload = {"service": "issuepilot", "ready": ready, **snapshot}
            code = 200 if self.path == "/healthz" or ready else 503
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def start_health(port, status, stale_after):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_type(status, stale_after))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
