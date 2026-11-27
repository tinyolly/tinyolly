#!/usr/bin/env bash
# Tear down what scripts/status.sh shows, in levels. DESTRUCTIVE, so it is a dry run until you confirm.
#
#   scripts/teardown.sh --level demos      # OpenTelemetry Demo, Istio ambient demo
#   scripts/teardown.sh --level stacks     # + TinyOlly itself (its kind deployment, data included)
#   scripts/teardown.sh --level cluster    # + the kind cluster
#   scripts/teardown.sh --level vms        # + stop the tinyolly Colima VM
#
# Options: --yes            run without asking (otherwise it prints the plan and asks; with no terminal it only prints)
#          --prune          also prune Docker build cache and dangling images on the VM
#          --prune-images   also remove ALL unused images (you will have to rebuild or re-pull)
#          --delete-vms     with --level vms: DELETE the VMs and their disks instead of stopping them (data loss)
# Only the things this project creates are touched (the kind cluster, Helm release
# my-otel-demo, the Istio demo namespaces). Other containers in the VM are listed, never removed,
# but stopping a VM stops them too.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
KIND_NAME="${KIND_CLUSTER:-tinyolly}"; KCTX="kind-$KIND_NAME"
CTXS="colima-tinyolly"
ISTIO_DEMO="$ROOT/../istio-ambient-demo"
LEVEL=""; YES=0; PRUNE=0; PRUNE_IMAGES=0; DELETE_VMS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --level) LEVEL="${2:-}"; shift ;;
    --yes) YES=1 ;;
    --prune) PRUNE=1 ;;
    --prune-images) PRUNE=1; PRUNE_IMAGES=1 ;;
    --delete-vms) DELETE_VMS=1 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
case "$LEVEL" in demos) N=1 ;; stacks) N=2 ;; cluster) N=3 ;; vms) N=4 ;;
  *) echo "usage: scripts/teardown.sh --level demos|stacks|cluster|vms [--prune] [--yes]   (--help for details)" >&2; exit 2 ;; esac
[ "$DELETE_VMS" = 1 ] && [ "$N" -lt 4 ] && { echo "--delete-vms needs --level vms" >&2; exit 2; }

B=$'\033[1m'; R=$'\033[31m'; Y=$'\033[33m'; D=$'\033[2m'; X=$'\033[0m'
docker_up() { docker --context "$1" info >/dev/null 2>&1; }
kube_up()   { kubectl --context "$KCTX" get ns >/dev/null 2>&1; }
STEP_DESC=(); STEP_CMD=()
add() { STEP_DESC+=("$1"); STEP_CMD+=("$2"); }
KUBE_OK=1
if kube_up && [ "$(kubectl config current-context 2>/dev/null)" != "$KCTX" ]; then
  KUBE_OK=0; echo "${Y}kubectl context is '$(kubectl config current-context)', not $KCTX: kind steps are skipped. Fix: kubectl config use-context $KCTX${X}"
fi

# ---- level 1: demos
if kube_up && [ "$KUBE_OK" = 1 ]; then
  helm --kube-context "$KCTX" list -A -o json 2>/dev/null | jq -e '.[] | select(.name=="my-otel-demo")' >/dev/null 2>&1 \
    && add "OpenTelemetry Demo on kind (helm my-otel-demo)" "k8s-otel-demo/02-cleanup-otel-demo-helm.sh"
  if { kubectl --context "$KCTX" get ns istio-system || kubectl --context "$KCTX" get ns boutique; } >/dev/null 2>&1 && [ -x "$ISTIO_DEMO/04-cleanup.sh" ]; then
    add "Istio ambient demo on kind (istio, shop, waypoint)" "(cd '$ISTIO_DEMO' && ./04-cleanup.sh)"
  fi
fi

# ---- level 2: TinyOlly itself
if [ "$N" -ge 2 ]; then
  if kube_up && [ "$KUBE_OK" = 1 ] && kubectl --context "$KCTX" get deploy tinyolly-ui >/dev/null 2>&1; then
    add "TinyOlly on kind (deployments, services, data volume)" "k8s/03-cleanup.sh --yes"
  fi
fi

# ---- level 3: the kind cluster
if [ "$N" -ge 3 ] && docker_up colima-tinyolly && DOCKER_CONTEXT=colima-tinyolly kind get clusters 2>/dev/null | grep -qx "$KIND_NAME"; then
  add "kind cluster '$KIND_NAME' (everything in it)" "DOCKER_CONTEXT=colima-tinyolly kind delete cluster --name $KIND_NAME"
fi

# ---- pruning (before any VM stops)
if [ "$PRUNE" = 1 ]; then
  for c in $CTXS; do
    docker_up "$c" || continue
    add "Prune Docker build cache and dangling images ($c)" "docker --context $c builder prune -af && docker --context $c image prune -f"
    [ "$PRUNE_IMAGES" = 1 ] && add "Remove ALL unused images ($c)" "docker --context $c image prune -af"
  done
fi

# ---- level 4: the VMs
OTHERS=""
if [ "$N" -ge 4 ]; then
  for p in tinyolly; do
    colima status -p "$p" >/dev/null 2>&1 || continue
    if [ "$DELETE_VMS" = 1 ]; then add "DELETE Colima VM '$p' and its disk (data loss)" "colima delete -p $p -f"
    else add "Stop Colima VM '$p'" "colima stop -p $p"; fi
    c="colima-$p"
    # containers other than the kind node
    docker_up "$c" && OTHERS="$OTHERS$(docker --context "$c" ps --format '{{.Names}}' 2>/dev/null \
      | awk -v ctx="$c" '$1!~/-control-plane$/ {print "  " $1 " (" ctx ")"}')"$'\n'
  done
fi

# ---- plan
if [ "${#STEP_DESC[@]}" -eq 0 ]; then echo "Nothing to tear down at level '$LEVEL'."; exit 0; fi
printf '%sPlan (level: %s)%s\n' "$B" "$LEVEL" "$X"
for i in "${!STEP_DESC[@]}"; do printf '  %d. %s\n     %s%s%s\n' "$((i+1))" "${STEP_DESC[$i]}" "$D" "${STEP_CMD[$i]}" "$X"; done
if [ "$N" -ge 4 ]; then
  printf '\n%sStopping a VM stops every container in it, including ones this project did not create:%s\n' "$Y" "$X"
  printf '%s' "$OTHERS" | grep -c . >/dev/null && printf '%s' "$OTHERS" | grep . || echo "  (none running besides this project's)"
fi
[ "$DELETE_VMS" = 1 ] && printf '\n%sDELETING VMs removes their disks: every image, volume and the kind cluster inside is gone for good.%s\n' "$R" "$X"

if [ "$YES" != 1 ]; then
  if [ -t 0 ]; then
    printf '\nRun these %d step(s)? [y/N] ' "${#STEP_DESC[@]}"; read -r ans
    case "$ans" in y|Y|yes) ;; *) echo "Not run."; exit 0 ;; esac
  else
    printf '\n(dry run: no terminal and no --yes, so nothing was changed)\n'; exit 0
  fi
fi

FAILED=0
for i in "${!STEP_DESC[@]}"; do
  printf '\n%s→ %s%s\n' "$B" "${STEP_DESC[$i]}" "$X"
  bash -c "${STEP_CMD[$i]}" || { FAILED=$((FAILED+1)); echo "${R}step failed (continuing): ${STEP_DESC[$i]}${X}"; }
done
printf '\n%d step(s) run, %d failed. Check the result: scripts/status.sh\n' "${#STEP_DESC[@]}" "$FAILED"
exit $((FAILED > 0))
