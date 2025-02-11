#!/usr/bin/env bash

set -euo pipefail

function run_docker_compose() {
    docker compose  \
        -f docker-compose.yml \
        -f docker-compose.dev.yml "$@"
}

cp .env.example .env
run_docker_compose build
run_docker_compose up -d
