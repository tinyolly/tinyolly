#!/usr/bin/env bash
# Toggle an OpenTelemetry Demo feature flag (served by flagd, which hot-reloads the file).
# Usage: ./03-set-flag.sh                      list flags and their current variant
#        ./03-set-flag.sh <flag> <variant>     e.g. paymentFailure 50%   |   emitRawPii on   |   cartFailure off
#        ./03-set-flag.sh --reset              turn every flag back to its default ("off")
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
F="$DIR/.demo/src/flagd/demo.flagd.json"
[ -f "$F" ] || { echo "Demo not cloned; run ./01-start-otel-demo.sh first." >&2; exit 1; }
python3 - "$F" "$@" <<'PY'
import json, sys
path, args = sys.argv[1], sys.argv[2:]
d = json.load(open(path))
flags = d["flags"]
if not args:
    for k, v in flags.items():
        print(f"{k:32} {v['defaultVariant']:6}  [{', '.join(v['variants'])}]  {v.get('description','')[:60]}")
    sys.exit(0)
if args[0] == "--reset":
    for v in flags.values():
        v["defaultVariant"] = "off"
else:
    flag, variant = args[0], args[1] if len(args) > 1 else None
    if flag not in flags: sys.exit(f"unknown flag '{flag}'")
    if variant not in flags[flag]["variants"]: sys.exit(f"variant must be one of {list(flags[flag]['variants'])}")
    flags[flag]["defaultVariant"] = variant
    print(f"{flag} -> {variant}")
with open(path, "w") as fh:        # in-place write (same inode) so flagd's file watch picks it up
    json.dump(d, fh, indent=2); fh.write("\n")
PY
