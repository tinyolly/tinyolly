# TinyOlly Docker Hub Migration Plan

## Overview
This plan outlines the strategy to:
1. Build production-ready Docker images for all TinyOlly components
2. Publish images to Docker Hub for public distribution
3. Migrate from local builds to using pre-built images from Docker Hub
4. Maintain backward compatibility with existing deployment workflows

---

## Current Architecture Analysis

### Existing Images
The project currently builds 5 custom images locally:

1. **tinyolly-python-base** - Base image with Python 3.12 + shared dependencies
2. **tinyolly-ui** - FastAPI web UI (inherits from python-base)
3. **tinyolly-otlp-receiver** - gRPC OTLP receiver (inherits from python-base)
4. **tinyolly-opamp-server** - Go-based OpAMP server (multi-stage build)
5. **otel-supervisor** - OpenTelemetry Collector + OpAMP supervisor

### External Dependencies
- `redis:7-alpine` - Used as-is from Docker Hub
- `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:latest`
- `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-opampsupervisor:latest`

---

## Phase 1: Docker Hub Repository Setup

### 1.1 Create Docker Hub Organization/Account
- **Recommended**: Create organization `tinyolly` on Docker Hub
- **Alternative**: Use personal account with prefix `tinyolly/`
- **Images to publish**:
  - `tinyolly/python-base`
  - `tinyolly/ui`
  - `tinyolly/otlp-receiver`
  - `tinyolly/opamp-server`
  - `tinyolly/otel-supervisor`

### 1.2 Repository Configuration
For each image:
- Set visibility: **Public**
- Add description from project README
- Add link to GitHub repository
- Configure automated builds (optional, see Phase 3)

---

## Phase 2: Image Build & Tagging Strategy

### 2.1 Tagging Convention
Implement semantic versioning with the following tags:

```
tinyolly/<image-name>:latest          # Latest stable release
tinyolly/<image-name>:v2.0.0          # Specific version
tinyolly/<image-name>:v2.0            # Minor version alias
tinyolly/<image-name>:v2              # Major version alias
tinyolly/<image-name>:dev             # Development/nightly builds
tinyolly/<image-name>:<git-sha>       # Specific commit (CI/CD)
```

### 2.2 Multi-Architecture Support
Build images for both:
- `linux/amd64` (Intel/AMD x86_64)
- `linux/arm64` (Apple Silicon, ARM servers)

Use Docker Buildx for multi-platform builds:
```bash
docker buildx create --name tinyolly-builder --use
docker buildx build --platform linux/amd64,linux/arm64 \
  -t tinyolly/python-base:latest \
  -t tinyolly/python-base:v2.0.0 \
  --push \
  -f dockerfiles/Dockerfile.tinyolly-python-base .
```

---

## Phase 3: Build Scripts for Docker Hub Publishing

### 3.1 New Build Script: `build-and-push-images.sh`

Located at `/docker/build-and-push-images.sh`:

```bash
#!/bin/bash
set -e

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}
PLATFORMS="linux/amd64,linux/arm64"

# Ensure buildx builder exists
docker buildx create --name tinyolly-builder --use 2>/dev/null || true
docker buildx use tinyolly-builder

echo "Building and pushing TinyOlly images to Docker Hub"
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo "Platforms: $PLATFORMS"
echo ""

# Build order matters: base image must be built first
IMAGES=(
  "python-base:Dockerfile.tinyolly-python-base"
  "ui:Dockerfile.tinyolly-ui:tinyolly-ui"
  "otlp-receiver:Dockerfile.tinyolly-otlp-receiver:tinyolly-otlp-receiver"
  "opamp-server:Dockerfile.tinyolly-opamp-server"
  "otel-supervisor:Dockerfile.otel-supervisor"
)

for image_config in "${IMAGES[@]}"; do
  IFS=':' read -r IMAGE_NAME DOCKERFILE BUILD_ARG <<< "$image_config"

  echo "Building $DOCKER_HUB_ORG/$IMAGE_NAME:$VERSION..."

  BUILD_CMD="docker buildx build --platform $PLATFORMS"
  BUILD_CMD="$BUILD_CMD -f dockerfiles/$DOCKERFILE"
  BUILD_CMD="$BUILD_CMD -t $DOCKER_HUB_ORG/$IMAGE_NAME:latest"
  BUILD_CMD="$BUILD_CMD -t $DOCKER_HUB_ORG/$IMAGE_NAME:$VERSION"

  if [ -n "$BUILD_ARG" ]; then
    BUILD_CMD="$BUILD_CMD --build-arg APP_DIR=$BUILD_ARG"
  fi

  BUILD_CMD="$BUILD_CMD --push ."

  eval $BUILD_CMD

  echo "✓ Pushed $DOCKER_HUB_ORG/$IMAGE_NAME:$VERSION"
  echo ""
done

echo "All images successfully built and pushed!"
```

### 3.2 Usage

```bash
# Push latest development build
cd docker
./build-and-push-images.sh dev

# Push versioned release
./build-and-push-images.sh v2.0.0

# Custom organization
DOCKER_HUB_ORG=myorg ./build-and-push-images.sh v2.0.0
```

---

## Phase 4: Migrate Dockerfiles to Use Pre-Built Base Images

### 4.1 Update Dockerfiles

**Current** (local build):
```dockerfile
FROM tinyolly-python-base:latest
```

**New** (Docker Hub):
```dockerfile
FROM tinyolly/python-base:latest
```

### 4.2 Files to Update

1. `/docker/dockerfiles/Dockerfile.tinyolly-ui`
   - Line 2: `FROM tinyolly/python-base:latest`

2. `/docker/dockerfiles/Dockerfile.tinyolly-otlp-receiver`
   - Line 2: `FROM tinyolly/python-base:latest`

3. `/docker/docker-compose-tinyolly-core.yml`
   - Update `build` sections to use `image` instead
   - Example:
     ```yaml
     tinyolly-ui:
       image: tinyolly/ui:latest
       # Remove 'build' section
     ```

4. `/docker-core-only/docker-compose-tinyolly-core.yml`
   - Same updates as above

---

## Phase 5: Update Deployment Scripts

### 5.1 Modify `docker/01-start-core.sh`

**Before**:
```bash
# Build the shared Python base image first
docker build -t tinyolly-python-base:latest -f dockerfiles/Dockerfile.tinyolly-python-base .
```

**After**:
```bash
# Pull latest images from Docker Hub
docker-compose -f docker-compose-tinyolly-core.yml pull
```

Remove local build logic; use `docker-compose pull` to fetch from Docker Hub.

### 5.2 New Script: `docker/use-local-builds.sh`

For development, provide option to build locally:

```bash
#!/bin/bash
# Temporarily override docker-compose.yml to use local builds
export COMPOSE_FILE=docker-compose-tinyolly-core-local.yml
echo "Using local builds. Run docker-compose up -d --build"
```

### 5.3 Create `docker/docker-compose-tinyolly-core-local.yml`

Copy of current docker-compose file with `build` sections intact for local development.

---

## Phase 6: Update Documentation

### 6.1 README.md Updates

Update Quick Start section:

**Before**:
```bash
cd docker
./01-start-core.sh  # Builds images locally
```

**After**:
```bash
cd docker
./01-start-core.sh  # Uses pre-built images from Docker Hub
```

Add new section:

```markdown
## Using Pre-Built Images

TinyOlly images are published to Docker Hub for easy deployment:

- `tinyolly/ui:latest` - Web UI
- `tinyolly/otlp-receiver:latest` - OTLP gRPC receiver
- `tinyolly/opamp-server:latest` - OpAMP configuration server
- `tinyolly/otel-supervisor:latest` - OpenTelemetry Collector

All images support `linux/amd64` and `linux/arm64` architectures.

### Local Development Builds

To build images locally instead of pulling from Docker Hub:

```bash
cd docker
./build-local-images.sh  # Build all images locally
docker-compose -f docker-compose-tinyolly-core-local.yml up -d
```
```

### 6.2 Add DOCKER_HUB.md

Create new documentation file explaining:
- Available images on Docker Hub
- Version tagging strategy
- How to build and publish (for maintainers)
- How to use specific versions

---

## Phase 7: Kubernetes Manifest Updates

### 7.1 Update k8s Deployment YAMLs

Change image references in all k8s manifests:

**Before**:
```yaml
spec:
  containers:
  - name: tinyolly-ui
    image: tinyolly-ui:latest
    imagePullPolicy: IfNotPresent  # Uses local Minikube images
```

**After**:
```yaml
spec:
  containers:
  - name: tinyolly-ui
    image: tinyolly/ui:latest
    imagePullPolicy: Always  # Pull from Docker Hub
```

### 7.2 Update `k8s/01-build-images.sh`

Add option to skip builds when using Docker Hub:

```bash
#!/bin/bash

if [ "$USE_DOCKERHUB" = "true" ]; then
  echo "Using images from Docker Hub (tinyolly/*)..."
  echo "Skipping local build step."
  exit 0
fi

# Existing build logic...
```

Usage:
```bash
USE_DOCKERHUB=true ./k8s/02-deploy-tinyolly.sh
```

---

## Phase 8: CI/CD Pipeline (Optional)

### 8.1 GitHub Actions Workflow

Create `.github/workflows/docker-publish.yml`:

```yaml
name: Build and Push Docker Images

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]
  pull_request:
    branches: [ main ]

jobs:
  build-and-push:
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

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: tinyolly/ui
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha

      - name: Build and push all images
        run: |
          cd docker
          ./build-and-push-images.sh ${{ steps.meta.outputs.version }}
```

### 8.2 Required Secrets

In GitHub repository settings, add:
- `DOCKERHUB_USERNAME` - Docker Hub username
- `DOCKERHUB_TOKEN` - Docker Hub access token

---

## Phase 9: Testing & Validation

### 9.1 Test Checklist

After migration, verify:

- [ ] All images pull successfully from Docker Hub
- [ ] `docker/01-start-core.sh` works with Docker Hub images
- [ ] `docker-demo/01-deploy-demo.sh` still functions
- [ ] `docker-ai-agent-demo/01-deploy-ai-demo.sh` still functions
- [ ] Kubernetes deployments work with Docker Hub images
- [ ] Multi-architecture images work on both amd64 and arm64
- [ ] No local build required for basic deployment
- [ ] Local development build option still available
- [ ] Documentation is accurate

### 9.2 Rollback Plan

If issues occur:
1. Revert Dockerfile `FROM` statements to `tinyolly-python-base:latest`
2. Revert docker-compose.yml to use `build:` sections
3. Keep Docker Hub images for future attempts

---

## Phase 10: Release Notes

### 10.1 Changelog Entry

Add to RELEASE-NOTES-v2.1.0.md:

```markdown
# TinyOlly v2.1.0 - Docker Hub Integration

## New Features

### Pre-Built Docker Images
- All TinyOlly images now published to Docker Hub under `tinyolly/*` namespace
- Multi-architecture support: linux/amd64 and linux/arm64
- No local build required for quick start deployments
- Faster deployment times (no compilation needed)

### Available Images
- `tinyolly/python-base` - Shared Python 3.12 base with common dependencies
- `tinyolly/ui` - Web UI and REST API
- `tinyolly/otlp-receiver` - OTLP gRPC receiver
- `tinyolly/opamp-server` - OpAMP configuration server
- `tinyolly/otel-supervisor` - OpenTelemetry Collector with supervisor

### Breaking Changes
- Default deployment now uses Docker Hub images (was: local builds)
- Local builds available via `docker-compose-tinyolly-core-local.yml`

## Migration Guide

Existing users: No action required. Running `./01-start-core.sh` will automatically pull from Docker Hub.

For local development builds:
```bash
cd docker
docker-compose -f docker-compose-tinyolly-core-local.yml up -d --build
```
```

---

## Implementation Timeline

### Immediate (Week 1)
1. Create Docker Hub organization/account
2. Create build and push script (`build-and-push-images.sh`)
3. Build and push initial images with `latest` and `v2.0.0` tags
4. Test pulling images on clean system

### Short-term (Week 2)
5. Update all Dockerfiles to use `tinyolly/*` images
6. Update docker-compose files
7. Update deployment scripts
8. Create local build variants for development
9. Test all deployment scenarios

### Medium-term (Week 3)
10. Update README and documentation
11. Create DOCKER_HUB.md guide
12. Update Kubernetes manifests
13. Comprehensive testing on both architectures
14. Create release notes

### Optional (Future)
15. Set up GitHub Actions CI/CD
16. Automated nightly builds with `dev` tag
17. Automated security scanning
18. Image size optimization

---

## File Changes Summary

### New Files
- `/docker/build-and-push-images.sh` - Build script for Docker Hub
- `/docker/docker-compose-tinyolly-core-local.yml` - Local build variant
- `/docker/use-local-builds.sh` - Helper for development
- `/DOCKER_HUB.md` - Documentation for Docker Hub usage
- `/.github/workflows/docker-publish.yml` - CI/CD pipeline (optional)

### Modified Files
- `/docker/dockerfiles/Dockerfile.tinyolly-ui` - Use Docker Hub base image
- `/docker/dockerfiles/Dockerfile.tinyolly-otlp-receiver` - Use Docker Hub base image
- `/docker/docker-compose-tinyolly-core.yml` - Use pre-built images
- `/docker-core-only/docker-compose-tinyolly-core.yml` - Use pre-built images
- `/docker/01-start-core.sh` - Pull instead of build
- `/README.md` - Document Docker Hub usage
- All k8s/*.yaml files - Update image references
- `/k8s/01-build-images.sh` - Add Docker Hub option

---

## Benefits

### For Users
- **Faster deployment** - No build time, instant pull
- **Smaller download** - Compressed layers, efficient caching
- **Multi-architecture** - Works on Apple Silicon and x86_64
- **Version pinning** - Use specific versions for reproducibility
- **No build tools** - Don't need Docker Buildx, Go compiler, etc.

### For Project
- **Wider adoption** - Lower barrier to entry
- **Professional image** - Standard distribution method
- **CI/CD ready** - Automated builds and testing
- **Version management** - Clear release artifacts
- **Community contribution** - Easier to test PRs

---

## Security Considerations

### Image Scanning
- Enable Docker Hub vulnerability scanning
- Add security scanning to CI/CD pipeline
- Pin base image versions (e.g., `python:3.12.1-slim` instead of `python:3.12-slim`)

### Access Control
- Use Docker Hub access tokens (not passwords) in CI/CD
- Limit token permissions to push only
- Rotate tokens regularly
- Use separate tokens for different environments

### Supply Chain
- Sign images with Docker Content Trust (optional)
- Provide SBOM (Software Bill of Materials) for compliance
- Document all base images and external dependencies

---

## Maintenance

### Regular Updates
- Rebuild images monthly for security patches
- Update base image versions quarterly
- Tag images with build date: `tinyolly/ui:v2.0.0-20250116`

### Deprecation Policy
- Keep last 3 major versions available
- Mark old versions as deprecated in Docker Hub
- Remove images older than 2 years (with notice)

---

## Questions to Resolve Before Implementation

1. **Docker Hub account**: Use organization `tinyolly` or personal account?
2. **Versioning**: Current version is v2.0.0 - start there or bump to v2.1.0?
3. **CI/CD**: Implement automated builds immediately or manual for first release?
4. **Base images**: Keep building custom python-base or use official `python:3.12-slim`?
5. **Backward compatibility**: Support old local-only build method indefinitely?
6. **Image retention**: How many versions to keep on Docker Hub?

---

## Estimated Effort

- **Setup & Initial Build**: 4-6 hours
- **Code Migration**: 6-8 hours
- **Documentation**: 4-6 hours
- **Testing**: 8-10 hours
- **CI/CD Setup**: 4-6 hours (optional)

**Total**: 26-36 hours (3-4 days of focused work)

---

## Success Metrics

After implementation:
- [ ] Images available on Docker Hub with both architectures
- [ ] Fresh clone deploys in <2 minutes (was: 10-15 minutes with builds)
- [ ] All existing deployment methods still work
- [ ] Documentation updated and clear
- [ ] At least 100 pulls on Docker Hub in first month
- [ ] Zero issues reported related to image migration
- [ ] CI/CD pipeline passing all tests
