# Mac size profile, picked from host RAM (override: PROFILE=lean|full). Source it; it sets HOST_GB, PROFILE, VM_CPU,
# VM_MEM (GiB), LOAD_USERS and BROWSER_TRAFFIC (demo load generator).
#   lean: under 48 GB RAM (e.g. a 24 GB Mac): 8 CPU / 12 GB VM, 15 users, no browser traffic, lean set of shop components.
#   full: 48 GB and up (e.g. a 64 GB Mac): host cores minus 2 / 40 GB VM, 40 users, browser traffic, every shop component.
HOST_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
HOST_CPU=$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 8)
PROFILE="${PROFILE:-$([ "$HOST_GB" -ge 48 ] && echo full || echo lean)}"
case "$PROFILE" in
  full) VM_CPU=$(( HOST_CPU > 2 ? HOST_CPU - 2 : 1 )); VM_MEM=40; LOAD_USERS=40; BROWSER_TRAFFIC=true ;;
  lean) VM_CPU=$(( HOST_CPU < 8 ? HOST_CPU : 8 ));     VM_MEM=12; LOAD_USERS=15; BROWSER_TRAFFIC=false ;;
  *) echo "PROFILE must be lean or full (got '$PROFILE')" >&2; return 2 2>/dev/null || exit 2 ;;
esac
