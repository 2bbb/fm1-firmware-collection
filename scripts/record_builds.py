#!/usr/bin/env python3
"""Merge a run's build results into catalog/builds.json.

    scripts/record_builds.py <results-dir>

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
    record[result["id"]] = {k: result[k] for k in ("repo", "commit", "status", "recipe", "run")}
record_path.write_text(json.dumps(dict(sorted(record.items())), indent=1) + "\n")
print(f"{len(record)} firmwares recorded")
