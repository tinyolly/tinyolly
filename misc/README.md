# misc: scripts kept but not part of the documented workflows

Moved here on 2026-11-25: scripts no docs page, README, CI job or documented script uses, and secondary stacks (core-only; Istio lives in its own repo). Each keeps its original path
under `misc/` and still works from here (paths point back at the original folder). Move one back if it becomes part of a workflow.

| Script | Was | What it does |
|---|---|---|
| `k8s/04-rebuild+deploy-ui.sh` | `k8s/` | rebuild the UI image, load into kind, restart the pod |
| `k8s-core-only/` | repo root | TinyOlly without its collector, for your own collector (docs: Your Own Collector Config) |
| `install-mkdocs.sh` | repo root | install MkDocs locally (`pip install -r docs/requirements.txt` does the same) |
| `scripts/check-trace-integrity.py` | `scripts/` | check stored traces for orphans and timing (API only) |
| `scripts/test-preset-behavior.py` | `scripts/` | end-to-end check of collector presets (needs Docker, ~2 min) |
