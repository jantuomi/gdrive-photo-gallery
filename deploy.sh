#!/bin/bash

# Use e.g. `direnv` to set the deploy variables

set -euxo pipefail

IMAGE=${OCI_REGISTRY}/gdrive-photo-gallery:latest

# Build
docker build --progress plain --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"

# Deploy
ssh "${SSH_SERVER}" "${UPDATE_COMMAND}"
