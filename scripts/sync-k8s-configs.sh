#!/usr/bin/env bash
# Regenerate the Kubernetes ConfigMaps from the single source of truth in docker/otelcol-configs/.
#   docker/otelcol-configs/config.yaml        -> k8s/otelcol-configs/config.yaml          (ConfigMap otel-collector-config)
#   docker/otelcol-configs/templates/*.yaml   -> k8s*/otelcol-configs/templates/templates.yaml (ConfigMap otelcol-templates)
# Run after editing any collector config/preset. CI fails if the generated files are stale.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import glob, os

def block(name, files):
    out = [f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {name}\ndata:\n"]
    for key, path in files:
        out.append(f"  {key}: |\n")
        for line in open(path).read().rstrip("\n").split("\n"):
            out.append(("    " + line if line.strip() else "") + "\n")
    return "".join(out)

src = "docker/otelcol-configs"
cfg = block("otel-collector-config", [("otel-collector-config.yaml", f"{src}/config.yaml")])
open("k8s/otelcol-configs/config.yaml", "w").write(cfg)

tpl = [(os.path.basename(p), p) for p in sorted(glob.glob(f"{src}/templates/*.yaml"))]
text = block("otelcol-templates", tpl)
for d in ("k8s", "k8s-core-only"):
    os.makedirs(f"{d}/otelcol-configs/templates", exist_ok=True)
    open(f"{d}/otelcol-configs/templates/templates.yaml", "w").write(text)
print("synced", len(tpl), "templates")
PY
