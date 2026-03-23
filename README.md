# Skill Telemetry POC

## Overview

This POC demonstrates how internal marketplace skills auto-emit OpenTelemetry data on every invocation via Claude Code. When a developer uses a skill from the internal marketplace, structured telemetry is automatically captured and shipped to a central analytics store (S3/Kafka) without any user action.

## Problem Statement

Our organisation publishes skills (code-review, credit-analysis etc) to an internal marketplace. Developers download these skills and use them in their projects via Claude Code. We need to capture invocation-level telemetry — who used which skill, on which project, how often, and what topics — without changing how developers work.

## Architecture

### How it works

1. Platform team publishes skill.md files to internal marketplace
2. Developer downloads skill into `.claude/skills/<skill-name>/SKILL.md`
3. Developer asks a question in Claude Code chat window
4. Claude agent auto-loads the skill from `.claude/skills/`
5. Claude completes the task AND silently runs `emit_telemetry.sh`
6. `emit_telemetry.sh` fires a curl POST to the OTel collector
7. `collector.py` receives the event and appends to `events.jsonl`
8. `ship_to_s3.py` ships events to `output/` (simulating S3/Kafka)

### Why curl POST + collector.py

- `curl` POST is the **messenger** — sends telemetry from Claude to the collector
- `collector.py` is the **post office** — receives, validates, persists events
- Together they form the OTel emission pipe
- In production: replace `collector.py` with a real OTel Collector and change the URL in `emit_telemetry.sh` — the skill never changes

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
│           ├── SKILL.md                  # Skill instructions + telemetry block
│           └── scripts/
│               └── emit_telemetry.sh     # curl POST — fires on every invocation
├── output/
│   └── skill_id=code-review-v1/
│       └── events.json                   # Hive-partitioned S3 simulation
├── collector.py                          # Local OTel collector (HTTP :4318)
├── ship_to_s3.py                         # Batch exporter — flushes buffer to output/
├── events.jsonl                          # Append-only local event buffer
└── README.md
```

## Components

### `.claude/skills/code-review/SKILL.md`
The skill file loaded by Claude Code. Contains skill instructions in the body and a hidden telemetry block that instructs Claude to silently call `emit_telemetry.sh` after every response. Supports two environments:
- **Claude Code** (bash available): silently runs the shell script
- **VS Code chat** (no bash): appends a `SKILL_TELEMETRY:` line scraped by an extension or CI hook

### `.claude/skills/code-review/scripts/emit_telemetry.sh`
Accepts four arguments (`intent`, `topics_csv`, `complexity`, `tokens_estimated`), generates a `trace_id` and `timestamp` at runtime, and fires a curl POST to the collector. Self-contained — no dependencies beyond `bash`, `curl`, and `python3`.

### `collector.py`
Lightweight HTTP server on port `4318` (standard OTLP HTTP port). Accepts `POST /skill-events`, parses the JSON body, pretty-prints to console, and appends the raw event to `events.jsonl`. In production, replace with a managed OTel Collector endpoint (Honeycomb, Datadog, Grafana Cloud).

### `events.jsonl`
Append-only local buffer. One JSON object per line. Cleared by `ship_to_s3.py` after each flush. Acts as the side-car buffer between the Claude agent and the exporter — equivalent to a Fluent Bit tail input in production.

### `ship_to_s3.py`
Reads `events.jsonl`, groups events by `skill_id`, and writes to Hive-partitioned output files (`output/skill_id=<x>/events.json`). Merges with any existing partition data so repeated runs accumulate rather than overwrite. Clears the buffer after shipping. In production, replace `output/` with an S3 sink (Glue, Vector, Lambda) — the partition scheme is Athena/Spark-compatible out of the box.

## Running locally

```bash
# 1. Start the collector
python3 collector.py &

# 2. Invoke a skill via Claude Code chat
#    (telemetry fires automatically via emit_telemetry.sh)

# 3. Ship buffered events to simulated S3
python3 ship_to_s3.py

# 4. Inspect the partition
cat output/skill_id=code-review-v1/events.json
```

## Production mapping

| POC component | Production equivalent |
|---|---|
| `.claude/skills/` | Internal skill marketplace |
| `SKILL.md` | Versioned, published skill artifact |
| `emit_telemetry.sh` | OTel SDK emission (zero-change to callers) |
| `collector.py` | OTel Collector / managed ingest endpoint |
| `events.jsonl` | Fluent Bit buffer / Kafka producer side-car |
| `ship_to_s3.py` | Glue job / Vector sink / Lambda exporter |
| `output/skill_id=x/` | S3 partition — queryable by Athena or Spark |
