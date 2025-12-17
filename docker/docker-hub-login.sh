#!/bin/bash
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

docker login

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Login successful!"
    echo ""
    echo "Next step: Run the build script"
    echo "  ./build-and-push-images.sh v2.0.0"
else
    echo ""
    echo "✗ Login failed. Please try again."
    exit 1
fi
