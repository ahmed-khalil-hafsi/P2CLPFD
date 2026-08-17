#!/bin/sh
# Sync the canonical root Prolog sources into the Python package.
# The root *.pl files are the source of truth; p2clpfd/pl/ is what
# ships in the pip package. Run this after editing any root .pl file.
set -eu
cd "$(dirname "$0")/.."
for f in facts solver csv_loader scenarios json_api tracer sensitivity multiperiod decompose; do
    [ -f "$f.pl" ] && cp "$f.pl" "p2clpfd/pl/$f.pl"
done
echo "p2clpfd/pl/ synced with root .pl sources"
