#!/usr/bin/env python3
"""Discover community M-VAVE FM-1 firmwares on GitHub and write catalog/firmwares.json.

Sources: the FM-1 Firmware Hub catalog, the aroum/fm1-custom-fw resource list and
GitHub repository search. Each repository is probed through the GitHub API for its
license, default-branch head, release packages and build entry point.

    scripts/catalog.py                      # refresh catalog/firmwares.json and CATALOG.md
    scripts/catalog.py --update-submodules  # also point firmwares/<owner>/<repo> at each head

Needs GITHUB_TOKEN (or GH_TOKEN) for the API rate limit. Standard library only.
"""
import argparse
import base64
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog" / "firmwares.json"
OVERRIDES = ROOT / "catalog" / "overrides.json"
TABLE = ROOT / "CATALOG.md"
HUB_CATALOG = "https://thefirmwarehub.com/catalog.json"
AROUM = "aroum/fm1-custom-fw"
SEARCHES = ["fm-1 firmware", "fm1 firmware", "m-vave fm1", "FM-1 felucca", "fwsc"]
REDISTRIBUTABLE = {
    "GPL-2.0", "GPL-3.0", "LGPL-3.0", "MIT", "MPL-2.0", "Apache-2.0", "BSD-2-Clause",
    "BSD-3-Clause", "Unlicense", "GPL-3.0-with-FM1-SDK-exception",
}
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def fetch(url, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "fm1-firmware-collection"}
    if TOKEN and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (404, 409, 451):
            return None
        raise


def api(path):
    body = fetch("https://api.github.com/" + path)
    return json.loads(body) if body else None


def discover():
    found = {}

    def add(repo, source, **extra):
        repo = repo.strip().removesuffix(".git").strip("/")
        if repo.count("/") != 1:
            return
        entry = found.setdefault(repo.lower(), {"repo": repo, "sources": []})
        if source not in entry["sources"]:
            entry["sources"].append(source)
        entry.update(extra)

    hub = json.loads(fetch(HUB_CATALOG, "application/json"))
    for item in hub.get("firmwares", []):
        repo = item.get("repo") or ""
        if not repo and str(item.get("source", "")).startswith("https://github.com/"):
            repo = item["source"].split("github.com/", 1)[1]
        if repo:
            add(repo, "hub", hub={k: item.get(k) for k in
                ("id", "name", "version", "product", "sha256", "size", "pkg", "release", "kind")})

    readme = api(f"repos/{AROUM}/readme")
    if readme:
        text = base64.b64decode(readme["content"]).decode("utf-8", "replace")
        start = text.find("## 1. Custom")
        end = text.find("## 2. ", start + 1)
        section = text[start:end] if start >= 0 else ""
        for repo in re.findall(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", section):
            add(repo, "aroum")

    for query in SEARCHES:
        result = api("search/repositories?per_page=100&q=" + urllib.parse.quote(query)) or {}
        for item in result.get("items", []):
            description = item.get("description") or ""
            if re.search(r"fm-?1", description, re.I) and re.search(r"firmware", description, re.I):
                add(item["full_name"], "search")
    return found


def recipe_for(paths):
    if "build.sh" in paths and "tools/get_toolchain.sh" in paths:
        return "felucca"
    if "firmware/build.sh" in paths:
        return "felucca-sub"
    if "build.sh" in paths:
        return "build-sh"
    if "Makefile" in paths:
        return "make"
    return "none"


def probe(entry, overrides):
    key = entry["repo"].lower()
    info = api(f"repos/{entry['repo']}")
    if not info:
        return {**entry, "status": "missing"}
    if info.get("private"):
        return {**entry, "status": "private"}
    repo = info["full_name"]
    branch = info["default_branch"]
    head = api(f"repos/{repo}/commits/{urllib.parse.quote(branch)}")
    tree = api(f"repos/{repo}/git/trees/{urllib.parse.quote(branch)}?recursive=1") or {}
    paths = {item["path"] for item in tree.get("tree", [])}
    releases = []
    for release in api(f"repos/{repo}/releases?per_page=5") or []:
        for asset in release.get("assets", []):
            if asset["name"].endswith(".fwsc"):
                releases.append({"tag": release["tag_name"], "name": asset["name"],
                                 "url": asset["browser_download_url"], "size": asset["size"],
                                 "prerelease": release["prerelease"], "published": release["published_at"]})
    license_id = (info.get("license") or {}).get("spdx_id")
    license_id = overrides["license"].get(key, license_id)
    recipe = overrides["recipe"].get(key, recipe_for(paths))
    tree_fwsc = sorted(p for p in paths if p.endswith(".fwsc"))
    has_build = bool(releases or tree_fwsc or (entry.get("hub") or {}).get("pkg"))
    redistributable = license_id in REDISTRIBUTABLE
    return {
        "id": repo.replace("/", "__"),
        "repo": repo,
        "url": info["html_url"],
        "description": info.get("description"),
        "sources": entry["sources"],
        "hub": entry.get("hub"),
        "license": license_id,
        "redistributable": redistributable,
        "fork_of": (info.get("parent") or {}).get("full_name"),
        "archived": info["archived"],
        "stars": info["stargazers_count"],
        "pushed": info["pushed_at"],
        "branch": branch,
        "head": head["sha"] if head else None,
        "has_submodules": ".gitmodules" in paths,
        "recipe": recipe,
        "upstream_releases": releases[:3],
        "tree_fwsc": tree_fwsc[:10],
        "has_build": has_build,
        "needs_ci_build": (not has_build) and redistributable and recipe != "none",
        "buildable": redistributable and recipe != "none",
        "path": f"firmwares/{repo}",
        "status": "ok",
    }


def write_table(entries):
    lines = ["# FM-1 community firmware catalog", "",
             "Generated by `scripts/catalog.py`. Builds: see the repository's Releases.", "",
             "| Firmware | License | Upstream build | Recipe | CI build |", "|---|---|---|---|---|"]
    for e in entries:
        upstream = "release" if e["upstream_releases"] else "in tree" if e["tree_fwsc"] else "hub" if (e.get("hub") or {}).get("pkg") else "—"
        ci = "yes" if e["needs_ci_build"] else "no (not redistributable)" if not e["redistributable"] else "—"
        name = (e.get("hub") or {}).get("name") or e["repo"].split("/")[1]
        lines.append(f"| [{name}]({e['url']}) `{e['repo']}` | {e['license'] or '?'} | {upstream} | {e['recipe']} | {ci} |")
    TABLE.write_text("\n".join(lines) + "\n")


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=check, capture_output=True, text=True).stdout


def update_submodules(entries):
    gitmodules = []
    wanted = {}
    for e in entries:
        if not e.get("head"):
            continue
        wanted[e["path"]] = e["head"]
        gitmodules += [f'[submodule "{e["path"]}"]', f'\tpath = {e["path"]}',
                       f'\turl = https://github.com/{e["repo"]}.git', f'\tbranch = {e["branch"]}',
                       "\tshallow = true"]
    (ROOT / ".gitmodules").write_text("\n".join(gitmodules) + "\n")
    current = {}
    for line in git("ls-files", "-s", "--", "firmwares").splitlines():
        mode, sha, _stage, path = line.split(None, 3)
        if mode == "160000":
            current[path] = sha
    for path in current.keys() - wanted.keys():
        git("update-index", "--force-remove", "--", path)
    for path, sha in wanted.items():
        if current.get(path) != sha:
            git("update-index", "--add", "--cacheinfo", f"160000,{sha},{path}")
    git("add", ".gitmodules")
    return len(wanted)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-submodules", action="store_true")
    args = parser.parse_args()
    overrides = json.loads(OVERRIDES.read_text())
    found = discover()
    for repo in overrides.get("include", []):
        found.setdefault(repo.lower(), {"repo": repo, "sources": ["manual"]})
    excluded = {k: v for k, v in found.items() if k in overrides["exclude"]}
    candidates = [v for k, v in found.items() if k not in overrides["exclude"]]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        probed = list(pool.map(lambda e: probe(e, overrides), candidates))
    # Renamed repositories can surface twice; keep one entry per canonical name.
    unique = {}
    for e in probed:
        if e["status"] == "ok" and e["repo"].lower() not in overrides["exclude"]:
            unique.setdefault(e["repo"].lower(), e)
    entries = sorted(unique.values(), key=lambda e: e["repo"].lower())
    missing = sorted(e["repo"] for e in probed if e["status"] == "missing")
    CATALOG.write_text(json.dumps({"firmwares": entries, "missing": missing,
                                   "excluded": sorted(excluded)}, indent=1, ensure_ascii=False) + "\n")
    write_table(entries)
    count = update_submodules(entries) if args.update_submodules else 0
    print(f"{len(entries)} firmwares, {sum(e['needs_ci_build'] for e in entries)} need a CI build, "
          f"{len(missing)} missing, {len(excluded)} excluded" + (f", {count} submodules" if count else ""))


if __name__ == "__main__":
    sys.exit(main())
