#!/usr/bin/env python3
"""Collect per-firmware build results into a release directory.

    scripts/publish.py <results-dir> <release-dir>

<results-dir>/<id>/result.json is written by the build job, next to the built .fwsc files.
Writes <release-dir>/<id>-<sha7>[-n].fwsc, index.json, SHA256SUMS and NOTES.md.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
catalog = {e["id"]: e for e in json.loads((root / "catalog" / "firmwares.json").read_text())["firmwares"]}
results_dir, release_dir = Path(sys.argv[1]), Path(sys.argv[2])
release_dir.mkdir(parents=True, exist_ok=True)
index, sums, ok, failed = [], [], [], []
for result_file in sorted(results_dir.glob("*/result.json")):
    result = json.loads(result_file.read_text())
    entry = catalog.get(result["id"], {})
    packages = sorted(result_file.parent.glob("*.fwsc"))
    if result["status"] != "success" or not packages:
        failed.append(result)
        continue
    for n, package in enumerate(packages):
        suffix = f"-{n + 1}" if len(packages) > 1 else ""
        name = f"{result['id']}-{result['commit'][:7]}{suffix}.fwsc"
        shutil.copyfile(package, release_dir / name)
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        sums.append(f"{digest}  {name}")
        index.append({"asset": name, "built_from": package.name, "repo": result["repo"],
                      "commit": result["commit"], "source": f"https://github.com/{result['repo']}/tree/{result['commit']}",
                      "license": entry.get("license"), "sha256": digest, "size": package.stat().st_size})
    ok.append(result)
(release_dir / "index.json").write_text(json.dumps({"builds": index, "failed": failed}, indent=1) + "\n")
(release_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n")
notes = ["Unofficial builds of community M-VAVE FM-1 firmwares, made by this repository's CI from the",
         "pinned source commit of each firmware's submodule. Not tested on hardware. Installing firmware",
         "is at your own risk; keep a way back to M-VAVE's official V15.", "",
         "Each package is the work of its authors under its own license; the source of each build is the",
         "commit listed below. Packages built with the JieLi AC79 SDK carry Apache-2.0 SDK files.", "",
         f"Built: {len(ok)}  Failed: {len(failed)}", "", "| Package | Source | License |", "|---|---|---|"]
for item in index:
    notes.append(f"| `{item['asset']}` | [{item['repo']}@{item['commit'][:7]}]({item['source']}) | {item['license']} |")
if failed:
    notes += ["", "Failed:", ""] + [f"- {r['repo']} ({r['recipe']}): {r['status']}" for r in failed]
(release_dir / "NOTES.md").write_text("\n".join(notes) + "\n")
print(f"{len(index)} packages from {len(ok)} firmwares, {len(failed)} failed")
