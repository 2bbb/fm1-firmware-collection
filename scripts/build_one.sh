#!/bin/sh
# Build one firmware from its submodule and copy the produced .fwsc package(s).
#   scripts/build_one.sh <path> <recipe> <outdir> [prepare-command]
# Needs JIELI_TOOLCHAIN (JieLi Linux toolchain) and AC79_SDK (JieLi AC79 SDK checkout).
set -eu
path=$1
recipe=$2
out=$3
mkdir -p "$out"
out=$(cd "$out" && pwd)
stamp=$(mktemp)
sleep 1
if [ -n "${4:-}" ]; then (cd "$path" && sh -c "$4"); fi
case "$recipe" in
  felucca|build-sh) (cd "$path" && sh ./build.sh) ;;
  felucca-sub)      (cd "$path/firmware" && sh ./build.sh) ;;
  make)             (cd "$path" && make) ;;
  *) echo "no build recipe: $recipe" >&2; exit 2 ;;
esac
found=0
for package in $(find "$path" -name '*.fwsc' -newer "$stamp" -not -path '*/.git/*' | sort); do
  cp "$package" "$out/"
  echo "built: $package"
  found=1
done
rm -f "$stamp"
if [ "$found" = 0 ]; then
  echo "the build finished without a new .fwsc" >&2
  exit 3
fi
