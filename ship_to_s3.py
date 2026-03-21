#!/usr/bin/env python3
"""Simulate shipping buffered telemetry events to partitioned S3 output."""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

BASE_DIR    = os.path.dirname(__file__)
EVENTS_FILE = os.path.join(BASE_DIR, "events.jsonl")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")


def load_events():
    events, skipped = [], 0
    with open(EVENTS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if "skill_id" in e:
                    events.append(e)
                else:
                    skipped += 1
            except json.JSONDecodeError:
                skipped += 1
    return events, skipped


def ship(events):
    buckets = defaultdict(list)
    for e in events:
        buckets[e["skill_id"]].append(e)

    shipped = {}
    for skill_id, batch in buckets.items():
        partition = os.path.join(OUTPUT_DIR, f"skill_id={skill_id}")
        os.makedirs(partition, exist_ok=True)
        out_path = os.path.join(partition, "events.json")

        # Merge with any existing events already in the partition
        existing = []
        if os.path.exists(out_path):
            with open(out_path) as f:
                existing = json.load(f)

        merged = existing + batch
        with open(out_path, "w") as f:
            json.dump(merged, f, indent=2)

        shipped[skill_id] = len(batch)

    return shipped


def clear_buffer():
    open(EVENTS_FILE, "w").close()


def main():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] ship_to_s3 starting")
    print(f"  Source : {EVENTS_FILE}")
    print(f"  Dest   : {OUTPUT_DIR}/\n")

    events, skipped = load_events()

    if not events:
        print("  No skill events found — nothing to ship.")
        return

    shipped = ship(events)

    print(f"  {'skill_id':<28} {'events shipped':<16} output path")
    print("  " + "-" * 72)
    for skill_id, count in shipped.items():
        path = f"output/skill_id={skill_id}/events.json"
        print(f"  {skill_id:<28} {count:<16} {path}")

    total = sum(shipped.values())
    print(f"\n  Total shipped : {total} event(s)")
    if skipped:
        print(f"  Skipped       : {skipped} line(s) (no skill_id / malformed)")

    clear_buffer()
    print(f"\n  events.jsonl cleared — buffer reset.")


if __name__ == "__main__":
    main()
