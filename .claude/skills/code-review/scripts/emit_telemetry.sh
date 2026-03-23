#!/usr/bin/env bash
# emit_telemetry.sh — fire a telemetry event for a code-review-v1 skill invocation.
# Usage: emit_telemetry.sh <intent> <topics_csv> <complexity> <tokens_estimated>
#   intent            : one-sentence description of what the user asked
#   topics_csv        : comma-separated topic tags, e.g. "sql-injection,auth"
#   complexity        : low | medium | high
#   tokens_estimated  : integer

INTENT="${1:-unknown}"
TOPICS_CSV="${2:-unknown}"
COMPLEXITY="${3:-medium}"
TOKENS="${4:-0}"
ENDPOINT="http://localhost:8318/skill-events"

TRACE_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PROJECT="$(basename "$(pwd)")"

# Convert comma-separated topics to a JSON array
TOPICS_JSON="$(python3 -c "
import json, sys
topics = [t.strip() for t in sys.argv[1].split(',') if t.strip()]
print(json.dumps(topics))
" "$TOPICS_CSV")"

curl -s -X POST "$ENDPOINT" \
  -H "Content-Type: application/json" \
  -d "{
    \"trace_id\":         \"$TRACE_ID\",
    \"timestamp\":        \"$TIMESTAMP\",
    \"skill_id\":         \"code-review-v1\",
    \"skill_version\":    \"1.0.0\",
    \"project\":          \"$PROJECT\",
    \"editor\":           \"claude-code\",
    \"intent\":           \"$INTENT\",
    \"topics\":           $TOPICS_JSON,
    \"complexity\":       \"$COMPLEXITY\",
    \"tokens_estimated\":  $TOKENS
  }" > /dev/null
