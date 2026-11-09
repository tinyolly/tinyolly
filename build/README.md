# TinyOlly Build Scripts

Centralized build scripts for all TinyOlly Docker images.

## Directory Structure

```
build/
├── README.md
├── dockerhub/                     # Build & push to Docker Hub
│   ├── 01-login.sh                # Step 1: Login to Docker Hub
│   ├── 02-build-all.sh            # Step 2: Build all images
│   ├── 02-build-core.sh           # Step 2: Build core images
│   ├── 02-build-ui.sh             # Step 2: Build UI only (quick iteration)
│   ├── 02-build-demo.sh           # Step 2: Build demo images
│   ├── 02-build-ebpf-demo.sh      # Step 2: Build eBPF demo images
│   ├── 02-build-ai-demo.sh        # Step 2: Build AI demo image
│   ├── 03-push-all.sh             # Step 3: Push all images
│   ├── 03-push-core.sh            # Step 3: Push core images
│   ├── 03-push-ui.sh              # Step 3: Push UI only
│   ├── 03-push-demo.sh            # Step 3: Push demo images
│   ├── 03-push-ebpf-demo.sh       # Step 3: Push eBPF demo images
│   └── 03-push-ai-demo.sh         # Step 3: Push AI demo image
└── local/                         # Local builds (kind)
    ├── build-core-kind.sh
    ├── build-demo-kind.sh
    └── build-ebpf-demo-kind.sh
```

## Quick Start - Docker Hub

```bash
cd build/dockerhub

# Step 1: Login to Docker Hub
./01-login.sh

# Step 2: Build images locally
./02-build-all.sh v2.1.0       # All images
# or
./02-build-core.sh v2.1.0      # Core only
# or
./02-build-ui.sh v2.1.0        # UI only (quick iteration)

# Step 3: Push to Docker Hub
./03-push-all.sh v2.1.0        # All images
# or
./03-push-core.sh v2.1.0       # Core only
# or
./03-push-ui.sh v2.1.0         # UI only
```

## Quick Start - Local (kind)

```bash
cd build/local

./build-core-kind.sh       # Core images
./build-demo-kind.sh       # Demo images
./build-ebpf-demo-kind.sh  # eBPF demo images
```

## Scripts Reference

### Step 1: Login

| Script | Description |
|--------|-------------|
| `01-login.sh` | Login to Docker Hub |

### Step 2: Build

| Script | Description |
|--------|-------------|
| `02-build-all.sh` | Build all images locally |
| `02-build-core.sh` | Build core TinyOlly images |
| `02-build-ui.sh` | Build UI image only (quick iteration) |
| `02-build-demo.sh` | Build demo app images |
| `02-build-ebpf-demo.sh` | Build eBPF demo images |
| `02-build-ai-demo.sh` | Build AI agent demo image |

### Step 3: Push

| Script | Description |
|--------|-------------|
| `03-push-all.sh` | Push all images to Docker Hub |
| `03-push-core.sh` | Push core images |
| `03-push-ui.sh` | Push UI image only |
| `03-push-demo.sh` | Push demo images |
| `03-push-ebpf-demo.sh` | Push eBPF demo images |
| `03-push-ai-demo.sh` | Push AI demo image |

## Images Reference

### Core Images

| Image | Description |
|-------|-------------|
| `tinyolly/python-base` | Shared Python base image |
| `tinyolly/ui` | Web UI |
| `tinyolly/otlp-receiver` | OTLP receiver service |
| `tinyolly/opamp-server` | OpAMP configuration server |
| `tinyolly/otel-supervisor` | OTel Collector supervisor |

### Demo Images

| Image | Description |
|-------|-------------|
| `tinyolly/demo-frontend` | Demo frontend app |
| `tinyolly/demo-backend` | Demo backend app |

### eBPF Demo Images

| Image | Description |
|-------|-------------|
| `tinyolly/ebpf-frontend` | eBPF demo frontend |
| `tinyolly/ebpf-backend` | eBPF demo backend |

### AI Demo Image

| Image | Description |
|-------|-------------|
| `tinyolly/ai-agent-demo` | AI agent demo app |

## Build Behavior

- **Build scripts**: Use `--no-cache` for fresh builds, `--load` to keep locally
- **Push scripts**: Push both `:version` and `:latest` tags
- **Multi-arch**: All images built for `linux/amd64` and `linux/arm64`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKER_HUB_ORG` | `tinyolly` | Docker Hub organization |

## CI/CD Integration

### GitHub Actions

```yaml
name: Build and Push Images

on:
  release:
    types: [published]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build images
        run: ./build/dockerhub/02-build-all.sh ${{ github.ref_name }}

      - name: Push images
        run: ./build/dockerhub/03-push-all.sh ${{ github.ref_name }}
```

### Required Secrets

| Secret | Description |
|--------|-------------|
| `DOCKERHUB_USERNAME` | Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |

### Creating a Docker Hub Access Token

1. Go to https://hub.docker.com/settings/security
2. Click "New Access Token"
3. Name it `tinyolly-ci` with Read & Write permissions
4. Add as repository secret

## Manual Release Checklist

```bash
cd build/dockerhub

# Step 1: Login
./01-login.sh

# Step 2: Build all images
./02-build-all.sh v2.1.0

# Step 3: Push to Docker Hub
./03-push-all.sh v2.1.0

# Step 4: Verify
docker pull tinyolly/ui:v2.1.0

# Step 5: Test Docker deployment
cd ../../docker
./01-start-core.sh

# Step 6: Test Kubernetes deployment
cd ../k8s
./02-deploy-tinyolly.sh
```
