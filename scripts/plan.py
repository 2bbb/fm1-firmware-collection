#!/usr/bin/env python3
"""Print the build matrix as JSON for GitHub Actions.

    scripts/plan.py missing        # no upstream package and not yet built at this commit (default)
    scripts/plan.py all            # every redistributable firmware with a build recipe
    scripts/plan.py only a/b,c/d   # the named repositories
"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
catalog = json.loads((root / "catalog" / "firmwares.json").read_text())
builds_path = root / "catalog" / "builds.json"
builds = json.loads(builds_path.read_text()) if builds_path.exists() else {}
scope = sys.argv[1] if len(sys.argv) > 1 else "missing"
names = {n.strip().lower() for n in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if n.strip()}
include = []
for e in catalog["firmwares"]:
    if not e.get("buildable"):
        continue
    if scope == "missing" and (not e["needs_ci_build"] or builds.get(e["id"], {}).get("commit") == e["head"]):
        continue
    if scope == "only" and e["repo"].lower() not in names:
        continue
    include.append({"id": e["id"], "repo": e["repo"], "path": e["path"], "recipe": e["recipe"]})
print(json.dumps({"include": include}))
