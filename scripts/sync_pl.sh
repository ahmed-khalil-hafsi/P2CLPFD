#!/bin/sh
# Keep p2clpfd/pl/ pointing at the canonical root Prolog sources.
# The root *.pl files are the source of truth. p2clpfd/pl/ holds symlinks to
# them, so there is normally nothing to do; this only replaces a plain copy
# (e.g. from an archive that dropped the links) with the current source.
set -eu
cd "$(dirname "$0")/.."
for f in facts solver csv_loader scenarios json_api tracer sensitivity multiperiod decompose; do
    [ -f "$f.pl" ] || continue
    if [ -L "p2clpfd/pl/$f.pl" ]; then
        continue
    fi
    cp "$f.pl" "p2clpfd/pl/$f.pl"
done
echo "p2clpfd/pl/ matches the root .pl sources"
