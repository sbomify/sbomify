#!/usr/bin/env bash

set -euo pipefail

export COMPOSE_PROFILES=dev

cp .env.example .env
docker compose build
docker compose up -d
