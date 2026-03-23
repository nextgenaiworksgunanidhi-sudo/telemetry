#!/usr/bin/env python3
"""OTel SDK-based telemetry collector for skill invocation events."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

EVENTS_FILE = Path(__file__).parent / "events.jsonl"
COLLECTOR_PORT = 8318
JAEGER_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
SERVICE_NAME = "skill-telemetry"


def build_tracer() -> trace.Tracer:
    resource = Resource.create({"service.name": SERVICE_NAME})
    exporter = OTLPSpanExporter(endpoint=JAEGER_OTLP_ENDPOINT)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(SERVICE_NAME)


def emit_span(tracer: trace.Tracer, event: dict[str, Any]) -> None:
    skill_id = event.get("skill_id", "unknown")
    with tracer.start_as_current_span(f"skill.invoke.{skill_id}") as span:
        span.set_attribute("skill.id", skill_id)
        span.set_attribute("skill.version", event.get("skill_version", ""))
        span.set_attribute("skill.intent", event.get("intent", ""))
        span.set_attribute("skill.complexity", event.get("complexity", ""))
        span.set_attribute("skill.tokens_estimated", int(event.get("tokens_estimated", 0)))
        span.set_attribute("skill.project", event.get("project", ""))
        span.set_attribute("skill.editor", event.get("editor", ""))
        span.set_attribute("skill.topics", json.dumps(event.get("topics", [])))
        span.set_attribute("trace.id", event.get("trace_id", ""))


def append_event(event: dict[str, Any]) -> None:
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


class TelemetryHandler(BaseHTTPRequestHandler):
    tracer: trace.Tracer  # injected at startup via build_tracer()

    def _parse_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            return None

    def _respond(self, status: int, body: bytes = b"") -> None:
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/skill-events":
            self._respond(404)
            return
        event = self._parse_body()
        if event is None:
            self._respond(400)
            return
        emit_span(self.__class__.tracer, event)
        append_event(event)
        ts = event.get("timestamp", datetime.now(timezone.utc).isoformat())
        print(f"[{ts}] skill={event.get('skill_id', 'unknown')}  span exported to Jaeger")
        self._respond(200, b'{"status":"ok"}')

    def log_message(self, fmt: str, *args: Any) -> None:
        pass


if __name__ == "__main__":
    TelemetryHandler.tracer = build_tracer()
    server = HTTPServer(("0.0.0.0", COLLECTOR_PORT), TelemetryHandler)
    print(f"OTel collector  → http://0.0.0.0:{COLLECTOR_PORT}/skill-events")
    print(f"Exporting spans → Jaeger OTLP at {JAEGER_OTLP_ENDPOINT}")
    print(f"Buffer file     → {EVENTS_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCollector stopped.")
