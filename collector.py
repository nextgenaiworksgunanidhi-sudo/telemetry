#!/usr/bin/env python3
"""Local telemetry receiver for skill invocation events."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone

EVENTS_FILE = os.path.join(os.path.dirname(__file__), "events.jsonl")
PORT = 4318


class TelemetryHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/skill-events":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            event = json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            self.send_response(400)
            self.end_headers()
            return

        # Pretty-print to console
        ts = event.get("timestamp", datetime.now(timezone.utc).isoformat())
        skill = event.get("skill", "unknown")
        status = event.get("status", "unknown")
        duration = event.get("duration_ms")

        print(f"\n[{ts}] skill={skill}  status={status}", end="")
        if duration is not None:
            print(f"  duration={duration}ms", end="")
        extra = {k: v for k, v in event.items()
                 if k not in {"timestamp", "skill", "status", "duration_ms"}}
        if extra:
            print(f"\n  {json.dumps(extra)}", end="")
        print()

        # Append raw line to events.jsonl
        with open(EVENTS_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, fmt, *args):
        # Suppress default access log noise
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), TelemetryHandler)
    print(f"Telemetry collector listening on http://0.0.0.0:{PORT}/skill-events")
    print(f"Appending events to: {EVENTS_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCollector stopped.")
