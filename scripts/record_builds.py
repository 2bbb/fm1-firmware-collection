#!/usr/bin/env python3
"""Merge a run's build results into catalog/builds.json.

    scripts/record_builds.py <results-dir> <release-dir>

The record keeps, per firmware, the last commit that was built and how it went, so the
next "missing" plan skips firmwares already built (or already failing) at that commit.
"""
import json
import sys
from pathlib import Path

record_path = Path(__file__).resolve().parent.parent / "catalog" / "builds.json"
record = json.loads(record_path.read_text()) if record_path.exists() else {}
for result_file in sorted(Path(sys.argv[1]).glob("*/result.json")):
    result = json.loads(result_file.read_text())
    entry = {k: result[k] for k in ("repo", "commit", "status", "recipe", "run")}
    previous = record.get(result["id"], {})
    if result["status"] == "success":
        entry["assets"] = sorted(p.name for p in Path(sys.argv[2]).glob(f"{result['id']}-{result['commit'][:7]}*.fwsc"))
    elif previous.get("assets"):
        # Keep pointing at the last good build while upstream is broken.
        entry["last_good"] = {k: previous.get(k) for k in ("commit", "assets")}
    elif previous.get("last_good"):
        entry["last_good"] = previous["last_good"]
    record[result["id"]] = entry
record_path.write_text(json.dumps(dict(sorted(record.items())), indent=1) + "\n")
print(f"{len(record)} firmwares recorded")
