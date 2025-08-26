#!/bin/bash
set -euo pipefail

DOCKER_ARGS=(-f docker-compose.yml -f docker-compose.dev.yml)

restart() {
    docker-compose "${DOCKER_ARGS[@]}" restart sbomify-backend sbomify-frontend
}

start() {
    docker-compose "${DOCKER_ARGS[@]}" up "$@"
}

build() {
    docker-compose "${DOCKER_ARGS[@]}" build "$@"
}

clean() {
    docker-compose "${DOCKER_ARGS[@]}" kill "$@"
    docker-compose "${DOCKER_ARGS[@]}" rm "$@"
    docker volume rm -f \
        sbomify_keycloak_data \
        sbomify_sbomify_minio_data \
        sbomify_sbomify_postgres_data \
        sbomify_sbomify_redis_data
}

case "${1:-}" in
    start)
        shift
        start "$@"
        ;;
    restart)
        shift
        start "$@"
        ;;
    build)
        shift
        build "$@"
        ;;
    clean)
        shift
        clean "$@"
        ;;
    *)
        echo "Usage: $0 {start|build|clean} [args...]"
        exit 1
        ;;
esac
