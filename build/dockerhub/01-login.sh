#!/bin/bash

# Always use the Colima docker daemon (profile: COLIMA_PROFILE, default tinyolly)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
# Helper script to login to Docker Hub
# Run this before building and pushing images

echo "Docker Hub Login"
echo "================"
echo ""
echo "You'll need your Docker Hub credentials:"
echo "  Username: (your Docker Hub username)"
echo "  Password: (use an access token, not your password)"
echo ""
echo "To create an access token:"
echo "  1. Go to https://hub.docker.com/settings/security"
echo "  2. Click 'New Access Token'"
echo "  3. Name it 'tinyolly-builds' with Read & Write permissions"
echo "  4. Use the token instead of your password below"
echo ""

# Without Docker Desktop, credentials go to the macOS keychain via docker-credential-osxkeychain:
#   brew install docker-credential-helper
#   ~/.docker/config.json must contain  "credsStore": "osxkeychain"  (not "desktop")
command -v docker-credential-osxkeychain >/dev/null || { echo "Missing helper: brew install docker-credential-helper"; exit 1; }

grep -q '"credsStore": *"osxkeychain"' ~/.docker/config.json 2>/dev/null || { echo 'Set "credsStore": "osxkeychain" in ~/.docker/config.json (not "desktop")'; exit 1; }
docker context inspect "$DOCKER_CONTEXT" >/dev/null 2>&1 || { echo "Docker context $DOCKER_CONTEXT missing: run scripts/colima-up.sh"; exit 1; }

docker login

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Login successful!"
    echo ""
    echo "Next steps:"
    echo ""
    echo "  Step 2 - Build images:"
    echo "    ./02-build-all.sh v2.1.0   # Build all images"
    echo "    ./02-build-core.sh v2.1.0  # Build core only"
    echo ""
    echo "  Step 3 - Push to Docker Hub:"
    echo "    ./03-push-all.sh v2.1.0    # Push all images"
    echo "    ./03-push-core.sh v2.1.0   # Push core only"
else
    echo ""
    echo "✗ Login failed. Please try again."
    exit 1
fi
