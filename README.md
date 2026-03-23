# Skill Telemetry POC

## Overview

This POC demonstrates how internal marketplace skills auto-emit real OpenTelemetry traces on every invocation via Claude Code. When a developer uses a skill from the internal marketplace, structured telemetry is automatically captured and shipped to Jaeger — without any user action.

## Problem Statement

Our organisation publishes skills (code-review, credit-analysis etc) to an internal marketplace. Developers download these skills and use them in their projects via Claude Code. We need to capture invocation-level telemetry — who used which skill, on which project, how often, and what topics — without changing how developers work.

## Architecture

```
Developer uses /code-review in Claude Code
        │
        ▼
SKILL.md instructs Claude to silently run emit_telemetry.sh
        │
        ▼
emit_telemetry.sh  ──curl POST──►  collector.py  (port 8318)
                                        │
                                        │  OTel SDK creates a real Span
                                        │  SpanKind.SERVER + StatusCode.OK/ERROR
                                        │
                                        ▼
                                  Jaeger  (OTLP HTTP port 4318)
                                        │
                                        ▼
                                  Jaeger UI  →  http://localhost:16686
```

### How it works

1. Platform team publishes `SKILL.md` files to internal marketplace
2. Developer downloads skill into `.claude/skills/<skill-name>/SKILL.md`
3. Developer asks a question in Claude Code chat window
4. Claude agent auto-loads the skill from `.claude/skills/`
5. Claude completes the task AND silently runs `emit_telemetry.sh`
6. `emit_telemetry.sh` fires a `curl POST` to `collector.py` on port 8318
7. `collector.py` uses the **OTel Python SDK** to create a real Span and export it to Jaeger via OTLP
8. `ship_to_s3.py` ships buffered events to `output/` (simulating S3/Kafka)

### SKILL.md frontmatter

Only these fields are officially recognised by Claude Code:

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | becomes the `/slash-command` |
| `description` | yes | how Claude decides when to invoke the skill |
| `allowed-tools` | no | restricts which tools the skill can use |
| `disable-model-invocation` | no | only user can invoke |
| `user-invocable` | no | only Claude can invoke |

Custom fields (`skill_id`, `version`, `owner_team`, `tags`, `telemetry_endpoint`) are ignored by the Claude Code runtime but are readable by marketplace tooling and CI/CD pipelines.

## Project Structure

```
telemetry/
├── .claude/
│   └── skills/
│       └── code-review/
│           ├── SKILL.md                  # Skill instructions + hidden telemetry block
│           └── scripts/
│               └── emit_telemetry.sh     # curl POST — fires on every invocation
├── output/
│   └── skill_id=code-review-v1/
│       └── events.json                   # Hive-partitioned S3 simulation
├── .venv/                                # Python virtualenv (OTel SDK deps)
├── collector.py                          # OTel SDK collector — creates spans, exports to Jaeger
├── ship_to_s3.py                         # Batch exporter — flushes buffer to output/
├── docker-compose.yml                    # Jaeger all-in-one
├── requirements.txt                      # opentelemetry-sdk + otlp-proto-http exporter
├── events.jsonl                          # Append-only local event buffer
└── README.md
```

## Components

### `.claude/skills/code-review/SKILL.md`
The skill file loaded by Claude Code. Contains skill instructions in the body and a hidden telemetry block that instructs Claude to silently call `emit_telemetry.sh` after every response. Supports two environments:
- **Claude Code** (bash available): silently runs the shell script
- **VS Code chat** (no bash): appends a `SKILL_TELEMETRY:` line scraped by an extension or CI hook

### `.claude/skills/code-review/scripts/emit_telemetry.sh`
Accepts four arguments (`intent`, `topics_csv`, `complexity`, `tokens_estimated`). At runtime it also captures `git config user.email` as `enduser.id`, generates a `trace_id` and `timestamp`, then fires a `curl POST` to `collector.py`. Self-contained — no dependencies beyond `bash`, `curl`, and `python3`.

### `collector.py`
HTTP server on port `8318`. Accepts `POST /skill-events`, converts the incoming JSON into a real **OpenTelemetry Span** using the Python OTel SDK, and exports it to Jaeger via OTLP HTTP on port `4318`. Also appends the raw event to `events.jsonl` for the S3 exporter.

**OTel fields captured:**

| OTel Field | Value |
|---|---|
| `service.name` | `skill-telemetry` |
| `service.version` | `1.0.0` |
| `span.kind` | `SERVER` |
| `status` | `OK` on success / `ERROR` on bad payload |
| `skill.id` | e.g. `code-review-v1` |
| `skill.version` | e.g. `1.0.0` |
| `skill.intent` | what the user asked |
| `skill.complexity` | `low` / `medium` / `high` |
| `skill.topics` | JSON array of tags |
| `skill.project` | project directory name |
| `skill.editor` | `claude-code` |
| `skill.tokens_estimated` | integer |
| `enduser.id` | git user email |

### `docker-compose.yml`
Runs Jaeger all-in-one with OTLP enabled. Exposes:
- `4317` — OTLP gRPC
- `4318` — OTLP HTTP (collector.py exports here)
- `16686` — Jaeger UI

### `events.jsonl`
Append-only local buffer. One JSON object per line. Cleared by `ship_to_s3.py` after each flush. Acts as the sidecar buffer between the Claude agent and the exporter — equivalent to a Fluent Bit tail input in production.

### `ship_to_s3.py`
Reads `events.jsonl`, groups events by `skill_id`, and writes to Hive-partitioned output files (`output/skill_id=<x>/events.json`). Merges with any existing partition data so repeated runs accumulate rather than overwrite. Clears the buffer after shipping. In production, replace `output/` with an S3 sink — the partition scheme is Athena/Spark-compatible out of the box.

## Running locally

```bash
# 1. Start Jaeger
docker compose up -d

# 2. Create virtualenv and install dependencies (first time only)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Start the collector
.venv/bin/python collector.py &

# 4. Invoke a skill via Claude Code chat
#    (telemetry fires automatically via emit_telemetry.sh)

# 5. View traces in Jaeger UI
open http://localhost:16686
# → Select service: skill-telemetry → Find Traces

# 6. Optionally ship buffered events to simulated S3
.venv/bin/python ship_to_s3.py
cat output/skill_id=code-review-v1/events.json
```

## Testing manually

Send a test event directly without invoking a skill:

```bash
curl -s -X POST http://localhost:8318/skill-events \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "aabbcc001122334455667788",
    "timestamp": "2026-03-23T10:00:00Z",
    "skill_id": "code-review-v1",
    "skill_version": "1.0.0",
    "project": "payments-service",
    "editor": "claude-code",
    "intent": "review authentication module for SQL injection",
    "topics": ["sql-injection", "auth", "security"],
    "complexity": "high",
    "tokens_estimated": 820,
    "enduser.id": "alice@company.com"
  }'
```

Then open http://localhost:16686, select service `skill-telemetry`, and click **Find Traces**.

## Production mapping

| POC component | Production equivalent |
|---|---|
| `.claude/skills/` | Internal skill marketplace |
| `SKILL.md` | Versioned, published skill artifact |
| `emit_telemetry.sh` | Same script — only the endpoint URL changes |
| `collector.py` | Managed OTel Collector (Honeycomb, Datadog, Grafana Cloud) |
| `docker-compose.yml` Jaeger | Jaeger / Grafana Tempo on your infra |
| `events.jsonl` | Fluent Bit buffer / Kafka producer sidecar |
| `ship_to_s3.py` | Glue job / Vector sink / Lambda exporter |
| `output/skill_id=x/` | S3 partition — queryable by Athena or Spark |
