# misc: scripts kept but not part of the documented workflows

Moved here on 2026-11-25: scripts no docs page, README, CI job or documented script uses, and secondary stacks (core-only; Istio lives in its own repo). Each keeps its original path
under `misc/` and still works from here (paths point back at the original folder). Move one back if it becomes part of a workflow.

| Script | Was | What it does |
|---|---|---|
| `docker/04-rebuild-ui.sh` | `docker/` | rebuild and restart only the UI container |
| `docker/04-cleanup-images.sh` | `docker/` | remove TinyOlly images from the Colima daemon |
| `k8s/04-rebuild+deploy-ui.sh` | `k8s/` | rebuild the UI image, load into kind, restart the pod |
| `docker-core-only/`, `k8s-core-only/` | repo root | TinyOlly without its collector, for your own collector (docs: Docker / Kubernetes, core-only section) |
| `install-mkdocs.sh` | repo root | install MkDocs locally (`pip install -r docs/requirements.txt` does the same) |
| `scripts/check-trace-integrity.py` | `scripts/` | check stored traces for orphans and timing (API only) |
| `scripts/test-preset-behavior.py` | `scripts/` | end-to-end check of collector presets (needs Docker, ~2 min) |
