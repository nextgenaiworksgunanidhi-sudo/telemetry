# Telemetry POC

This POC demonstrates how internal marketplace skills auto-emit OpenTelemetry data on every invocation.

## Overview

- Skills live in `.claude/skills/` as `.md` files
- When invoked via Claude Code, each skill emits a telemetry event via `curl` to a central collector running locally
- Events are buffered in `events.jsonl` and shipped to a simulated S3 output folder

## Structure

```
telemetry/
├── .claude/
│   └── skills/        # Marketplace skill definitions (.md files)
├── collector/         # Telemetry receiver — accepts and stores incoming events
├── output/            # Simulated S3 output — flushed batches land here
├── events.jsonl       # Local event buffer — append-only, one JSON event per line
└── README.md
```

## How it works

1. A skill in `.claude/skills/` is invoked through Claude Code
2. The skill's prompt includes a `curl` command that POSTs an OpenTelemetry-compatible JSON event to the local collector
3. The collector appends the event to `events.jsonl`
4. A separate flush process reads `events.jsonl` and writes batched output files to `output/`, simulating an S3 upload
