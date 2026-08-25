"""
Merge several benchmark JSON files into one.

Sweeps get run separately — a timeout budget that suits a 3,000-item run
wastes twenty minutes on a small one — so the results arrive in pieces.
This stitches them back together for the chart.

    python scripts/merge_bench.py out.json in1.json in2.json ...

Records for the same sweep are combined and sorted by size; a later file
wins on ties, so re-running one size overwrites the older measurement.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write(__doc__)
        return 2

    out_path, *in_paths = sys.argv[1:]
    config: dict = {}
    sweeps: dict[str, dict[tuple, dict]] = {}

    for path in in_paths:
        with open(path) as fh:
            payload = json.load(fh)
        config.update(payload.get("config", {}))
        for sweep, records in payload.get("results", {}).items():
            bucket = sweeps.setdefault(sweep, {})
            for record in records:
                # Size is (items, demand): the demand sweeps vary demand at
                # one item, the rest vary items at fixed demand.
                bucket[(record.get("items"), record.get("demand"))] = record

    merged = {
        sweep: [rec for _, rec in sorted(bucket.items())]
        for sweep, bucket in sweeps.items()
    }
    with open(out_path, "w") as fh:
        json.dump({"config": config, "results": merged}, fh, indent=2)

    for sweep, records in merged.items():
        done = sum(1 for r in records if r.get("seconds") is not None)
        print(f"  {sweep}: {len(records)} points ({done} completed)")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
