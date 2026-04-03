#!/bin/bash
set -euo pipefail

COMPOSE_FILE="docker-compose.tests.yml"
SCREENCASTS_DIR="screencasts"
OUTPUT_DIR="$SCREENCASTS_DIR/output"

# Detect container runtime
if command -v podman >/dev/null 2>&1; then
    RUNTIME="podman"
elif command -v docker >/dev/null 2>&1; then
    RUNTIME="docker"
else
    echo "Error: Neither podman nor docker is available."
    exit 1
fi

SERVICES_STARTED=false

compose() {
    $RUNTIME compose -f "$COMPOSE_FILE" "$@"
}

build_frontend() {
    echo "Building frontend assets..."
    bun run copy-deps && bun x vite build
}

teardown_services() {
    if [ "$SERVICES_STARTED" = true ]; then
        echo "Stopping test services..."
        compose down
    fi
}

trap teardown_services EXIT

ensure_services() {
    echo "Building and starting test services..."
    compose up -d --build
    SERVICES_STARTED=true
    echo "Waiting for services to be healthy..."
    compose exec tests python -c "
import socket, time
while True:
    try:
        s = socket.create_connection(('172.25.0.10', 5432), timeout=2)
        s.close(); break
    except OSError:
        time.sleep(1)
"
}

ensure_ffmpeg() {
    if ! compose exec tests bash -c "test -f /root/.cache/ms-playwright/ffmpeg-*/ffmpeg-linux" 2>/dev/null; then
        echo "Installing Playwright ffmpeg (first run only)..."
        compose exec tests uv run playwright install ffmpeg
    fi
}

run_screencast() {
    local file="$1"
    local basename
    basename=$(basename "$file" .py)
    echo "Recording: $file"
    compose exec tests uv run pytest "$file" \
        --override-ini="python_files=*.py" \
        --override-ini="python_functions=$basename" \
        -s
}

clean_temp_videos() {
    # Playwright generates random-named .webm files alongside our named ones.
    # Keep only files whose names match a screencast script.
    for webm in "$OUTPUT_DIR"/*.webm; do
        [ -f "$webm" ] || continue
        local name
        name=$(basename "$webm" .webm)
        if [ ! -f "$SCREENCASTS_DIR/${name}.py" ]; then
            rm -f "$webm"
        fi
    done
}

list_screencasts() {
    find "$SCREENCASTS_DIR" -maxdepth 1 -name "*.py" ! -name "conftest.py" -exec basename {} \; | sort
}

usage() {
    cat <<EOF
Usage: $0 [command] [args...]

Commands:
  all                   Record all screencasts
  <filename>            Record a single screencast (e.g. workspace_deletion.py)
  list                  List available screencast scripts
  clean                 Remove all recorded videos and temp files

Examples:
  $0 all
  $0 workspace_deletion.py
  $0 list
  $0 clean
EOF
}

case "${1:-}" in
    all)
        build_frontend
        ensure_services
        ensure_ffmpeg
        for file in "$SCREENCASTS_DIR"/*.py; do
            [ -f "$file" ] || continue
            [[ "$(basename "$file")" == "conftest.py" ]] && continue
            run_screencast "$file"
        done
        clean_temp_videos
        echo "Done. Recordings in $OUTPUT_DIR/"
        ls -lh "$OUTPUT_DIR"/*.webm 2>/dev/null
        ;;
    list)
        echo "Available screencasts:"
        list_screencasts
        ;;
    clean)
        echo "Removing all videos from $OUTPUT_DIR/"
        find "$OUTPUT_DIR" -name "*.webm" -delete 2>/dev/null || true
        echo "Done."
        ;;
    *.py)
        file="$SCREENCASTS_DIR/$1"
        if [ ! -f "$file" ]; then
            echo "Error: $file not found"
            echo ""
            echo "Available screencasts:"
            list_screencasts
            exit 1
        fi
        build_frontend
        ensure_services
        ensure_ffmpeg
        run_screencast "$file"
        clean_temp_videos
        echo "Done. Recording at $OUTPUT_DIR/${1%.py}.webm"
        ;;
    ""|help|--help|-h)
        usage
        ;;
    *)
        echo "Error: Unknown command '$1'"
        echo ""
        usage
        exit 1
        ;;
esac
