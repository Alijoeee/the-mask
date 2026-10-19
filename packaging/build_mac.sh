#!/usr/bin/env bash
# Builds "The MASK.app" with Briefcase: ad-hoc signed, no installer, and a zip of it in dist/.
#
#     bash packaging/build_mac.sh
#
# It works in the repository this file is in, wherever it is run from, and every run is a clean
# build: the folder Briefcase made last time is removed first (Briefcase would otherwise keep the
# old app and carry on building that, not the code as it is now).
#
# The app is made of the package versions in uv.lock, the ones the tests run on. The script writes
# them to build/constraints.txt, which pyproject.toml has pip keep to (left alone, pip takes the
# newest version of every package that nothing pins), and checks the finished app against the lock
# before it makes the zip.
#
# The build needs the network, once: Briefcase fetches its app template, its Python for macOS and
# the pinned wheels (the language model's from GitHub) and keeps them in
# ~/Library/Caches/org.beeware.briefcase and pip's cache, so a second build is much faster. The
# finished app never uses the network. Run it in a folder that iCloud does not sync: Briefcase
# stops with an error in one that it does.
#
# The result is build/themask/macos/app/The MASK.app and its zip in dist/.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

rm -rf build/themask
rm -f dist/*.app.zip

mkdir -p build
uv export --locked --no-dev --no-hashes --no-emit-project --no-annotate --format requirements-txt -o build/constraints.txt --quiet

uv run briefcase create macOS app --no-input
uv run briefcase build macOS app --no-input
uv run python -m tools.check_bundle_lock "build/themask/macos/app/The MASK.app"
uv run briefcase package macOS app -p zip --adhoc-sign --no-input

shopt -s nullglob
zips=(dist/*.app.zip)
if [ "${#zips[@]}" -eq 0 ]; then
    echo "briefcase package made no zip in dist/." >&2
    exit 1
fi

echo
echo "The app: $PWD/build/themask/macos/app/The MASK.app"
for zip in "${zips[@]}"; do
    echo "The zip: $PWD/$zip"
done
if commit=$(git rev-parse --short HEAD 2>/dev/null); then
    echo "Built from commit $commit"
    if [ -n "$(git status --porcelain)" ]; then
        echo "WARNING: there are changes that are not committed, so this is not exactly that commit." >&2
    fi
else
    echo "Built from a folder that is not a git checkout."
fi
