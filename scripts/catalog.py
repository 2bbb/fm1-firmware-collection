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
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
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


def fetch(url, accept="application/vnd.github+json", data=None):
    headers = {"Accept": accept, "User-Agent": "fm1-firmware-collection"}
    if TOKEN and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(url, headers=headers, data=data)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (404, 409, 451):
                return None
            # Primary and secondary rate limits answer 403/429; back off and retry.
            if error.code not in (403, 429, 500, 502, 503) or attempt == 5:
                raise
            wait = error.headers.get("Retry-After") or ""
            reset = error.headers.get("X-RateLimit-Reset") or ""
            if error.headers.get("X-RateLimit-Remaining") == "0" and reset.isdigit():
                # Primary limit: wait for the window to reset rather than burning the retries.
                time.sleep(max(int(reset) - time.time(), 0) + 5)
            else:
                time.sleep(min(int(wait) if wait.isdigit() else 15 * 2 ** attempt, 300))


def api(path):
    body = fetch("https://api.github.com/" + path)
    return json.loads(body) if body else None


REPO_FIELDS = """
  nameWithOwner url description isPrivate isArchived stargazerCount pushedAt
  parent { nameWithOwner }
  licenseInfo { spdxId }
  defaultBranchRef { name target { oid } }
  releases(first: 5, orderBy: {field: CREATED_AT, direction: DESC}) {
    nodes { tagName isPrerelease publishedAt releaseAssets(first: 30) { nodes { name downloadUrl size } } }
  }
"""


def repo_metadata(repos):
    """Fetch repository metadata 25 at a time through GraphQL: one request per batch."""
    meta = {}
    repos = list(repos)
    for i in range(0, len(repos), 25):
        batch = repos[i:i + 25]
        parts = []
        for n, repo in enumerate(batch):
            owner, name = repo.split("/", 1)
            parts.append(f"r{n}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{{REPO_FIELDS}}}")
        query = "query {" + "\n".join(parts) + "}"
        body = fetch("https://api.github.com/graphql", data=json.dumps({"query": query}).encode())
        result = json.loads(body) if body else {}
        for n, repo in enumerate(batch):
            meta[repo.lower()] = (result.get("data") or {}).get(f"r{n}")
    return meta


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

    readme = fetch(f"https://raw.githubusercontent.com/{AROUM}/HEAD/README.md", "text/plain")
    if readme:
        text = readme.decode("utf-8", "replace")
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


def probe(entry, info, previous, overrides):
    key = entry["repo"].lower()
    if not info:
        return {**entry, "status": "missing"}
    if info["isPrivate"]:
        return {**entry, "status": "private"}
    repo = info["nameWithOwner"]
    branch_ref = info.get("defaultBranchRef") or {}
    branch = branch_ref.get("name")
    head = (branch_ref.get("target") or {}).get("oid")
    if not head:
        return {**entry, "status": "missing"}
    old = previous.get(repo.lower()) or {}
    if old.get("head") == head and "auto_recipe" in old:
        # Unchanged since the last run: reuse what the tree said instead of asking again.
        auto_recipe, tree_fwsc, has_submodules = old["auto_recipe"], old["tree_fwsc"], old["has_submodules"]
    else:
        tree = api(f"repos/{repo}/git/trees/{head}?recursive=1") or {}
        paths = {item["path"] for item in tree.get("tree", [])}
        auto_recipe = recipe_for(paths)
        tree_fwsc = sorted(p for p in paths if p.endswith(".fwsc"))[:10]
        has_submodules = ".gitmodules" in paths
    releases = []
    for release in (info.get("releases") or {}).get("nodes", []):
        for asset in (release.get("releaseAssets") or {}).get("nodes", []):
            if asset["name"].endswith(".fwsc"):
                releases.append({"tag": release["tagName"], "name": asset["name"], "url": asset["downloadUrl"],
                                 "size": asset["size"], "prerelease": release["isPrerelease"],
                                 "published": release["publishedAt"]})
    license_id = overrides["license"].get(key, (info.get("licenseInfo") or {}).get("spdxId"))
    recipe = overrides["recipe"].get(key, auto_recipe)
    has_build = bool(releases or tree_fwsc or (entry.get("hub") or {}).get("pkg"))
    redistributable = license_id in REDISTRIBUTABLE
    return {
        "id": repo.replace("/", "__"),
        "repo": repo,
        "url": info["url"],
        "description": info.get("description"),
        "sources": entry["sources"],
        "hub": entry.get("hub"),
        "license": license_id,
        "redistributable": redistributable,
        "fork_of": (info.get("parent") or {}).get("nameWithOwner"),
        "archived": info["isArchived"],
        "stars": info["stargazerCount"],
        "pushed": info["pushedAt"],
        "branch": branch,
        "head": head,
        "has_submodules": has_submodules,
        "auto_recipe": auto_recipe,
        "recipe": recipe,
        "prepare": overrides.get("prepare", {}).get(key),
        "upstream_releases": releases[:3],
        "tree_fwsc": tree_fwsc,
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
    previous = {}
    if CATALOG.exists():
        previous = {e["repo"].lower(): e for e in json.loads(CATALOG.read_text())["firmwares"]}
    meta = repo_metadata(e["repo"] for e in candidates)
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        probed = list(pool.map(lambda e: probe(e, meta.get(e["repo"].lower()), previous, overrides), candidates))
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
