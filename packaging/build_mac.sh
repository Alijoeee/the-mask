#!/usr/bin/env bash
# Builds "The MASK.app" with Briefcase: ad-hoc signed, no installer, and a zip of it in dist/.
#
#     bash packaging/build_mac.sh
#
# It works in the repository this file is in, wherever it is run from, and every run is a clean
# build: the folder Briefcase made last time is removed first (Briefcase would otherwise keep the
# old app and carry on building that, not the code as it is now).
#
# The build needs the network, once: Briefcase fetches its app template, its Python for macOS and
# the pinned wheels (the language model's from GitHub) and keeps them in
# ~/Library/Caches/org.beeware.briefcase and pip's cache, so a second build is much faster. The
# finished app never uses the network.
#
# The result is build/themask/macos/app/The MASK.app and its zip in dist/.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

rm -rf build/themask
rm -f dist/*.app.zip

uv run briefcase create macOS app --no-input
uv run briefcase build macOS app --no-input
uv run briefcase package macOS app -p zip --adhoc-sign --no-input

echo
echo "The app: $PWD/build/themask/macos/app/The MASK.app"
for zip in dist/*.app.zip; do
    echo "The zip: $PWD/$zip"
done
