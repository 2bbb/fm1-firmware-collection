# fm1-firmware-collection

Every community firmware for the M-VAVE FM-1 that can be found on GitHub, as git submodules pinned to each
project's default-branch head, with CI builds for the ones that publish no package of their own.

- **Catalog:** [CATALOG.md](CATALOG.md) (table), [catalog/firmwares.json](catalog/firmwares.json) (data)
- **Sources:** `firmwares/<owner>/<repo>` submodules
- **Builds:** the repository's [Releases](../../releases) (`builds-YYYYMMDD-N`), each with `index.json` and `SHA256SUMS`

Not affiliated with M-VAVE or with the firmware authors. The builds are untested on hardware; installing
firmware is at your own risk, so keep a way back to M-VAVE's official V15.

## How it works

| Step | Where |
|---|---|
| Discover firmwares from the [FM-1 Firmware Hub](https://thefirmwarehub.com/) catalog, [aroum/fm1-custom-fw](https://github.com/aroum/fm1-custom-fw) and GitHub search; probe license, releases and build entry point | `scripts/catalog.py` |
| Manual corrections: non-firmware repositories, license and recipe fixes | `catalog/overrides.json` |
| Move each submodule to its upstream head (gitlinks only, nothing is cloned) | `scripts/catalog.py --update-submodules` |
| Nightly: refresh, commit, then build what is new | `.github/workflows/update.yml` |
| Build with the JieLi Linux toolchain and the AC79 SDK, publish a release | `.github/workflows/build.yml` |

A firmware is built when it has no upstream package (no `.fwsc` in a release, in its tree or on the Hub), its
license allows redistribution, and it has a known build entry point (`build.sh` of the Felucca family,
`firmware/build.sh`, or a `Makefile`). Each build is recorded in `catalog/builds.json` with its commit, so
it is not rebuilt until upstream moves. Run **build** by hand with `scope: all` to build every buildable
firmware, or `scope: only` with a list of repositories.

Upstream packages are listed in the catalog with their URLs; they are not re-hosted here. Firmwares without
a license file are listed and pinned but never built or redistributed.

## Local use

```sh
git clone https://github.com/2bbb/fm1-firmware-collection.git
cd fm1-firmware-collection
git submodule update --init --depth 1 firmwares/hugelton/Felucca
GITHUB_TOKEN=$(gh auth token) python3 scripts/catalog.py --update-submodules
```

## License

The scripts and workflows in this repository: MIT ([LICENSE](LICENSE)). Each firmware keeps its own license;
see the catalog and each submodule.
