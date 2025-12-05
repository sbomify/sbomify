#!/bin/bash
set -euo pipefail

# Detect container runtime - prefer podman, fallback to docker
if command -v podman >/dev/null 2>&1; then
    CONTAINER_RUNTIME="podman"
elif command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME="docker"
else
    echo "Error: Neither podman nor docker is available. Please install one of them."
    exit 1
fi

DOCKER_ARGS=(-f docker-compose.yml -f docker-compose.dev.yml)

restart() {
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" restart sbomify-backend sbomify-frontend
}

start() {
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" up --force-recreate "$@"
}

stop() {
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" stop "$@"
}

end() {
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" down "$@"
}

build() {
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" build "$@"
}

clean() {
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" kill "$@"
    $CONTAINER_RUNTIME compose "${DOCKER_ARGS[@]}" rm "$@"
    $CONTAINER_RUNTIME volume rm -f \
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
    stop)
        shift
        stop "$@"
        ;;
    end)
        shift
        end "$@"
        ;;
    restart)
        shift
        restart "$@"
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
        echo "Usage: $0 {start|stop|end|restart|build|clean} [args...]"
        exit 1
        ;;
esac
