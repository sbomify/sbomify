#!/usr/bin/env bash

set -euo pipefail

function run_docker_compose() {
    docker compose  \
        -f docker-compose.yml \
        -f docker-compose.dev.yml "$@"
}

run_docker_compose up -d --build
