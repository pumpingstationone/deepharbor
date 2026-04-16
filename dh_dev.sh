#!/usr/bin/env bash
#
# dh_dev.sh — Manage the Deep Harbor dev environment
#
# Usage:
#   ./dh_dev.sh setup       One-time setup: copy configs, generate seed data, start
#   ./dh_dev.sh start       Build and start the dev environment
#   ./dh_dev.sh stop        Stop containers (database persists)
#   ./dh_dev.sh reset       Full reset: remove volumes, rebuild, start (re-seeds DB)
#   ./dh_dev.sh status      Show container status
#   ./dh_dev.sh clean       Remove all dev artifacts (containers, volumes, configs, seed data)
#
# After running setup once, use start/stop/reset for day-to-day operations.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export GIT_VERSION="$(git branch --show-current)-$(git rev-parse --short HEAD) $(date +%Y-%m-%d)"

COMPOSE="docker compose -f docker-compose.yaml -f docker-compose.dev.yml"

usage() {
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  setup    One-time first-run setup (copy configs, seed data, build, start)"
    echo "  start    Build and start the dev environment"
    echo "  stop     Stop containers (database volume preserved)"
    echo "  reset    Full reset: stop, remove volumes, rebuild, start"
    echo "  clean    Remove all dev artifacts (return to fresh clone state)"
    echo "  status   Show container status"
    echo ""
    echo "Examples:"
    echo "  $0 setup              First time? Run this."
    echo "  $0 start              Start after a previous stop"
    echo "  $0 stop               Stop without losing data"
    echo "  $0 reset              Nuke everything and start fresh"
    echo "  $0 clean              Remove everything, back to fresh clone"
    echo "  $0 status             Check what's running"
}

print_access() {
    echo ""
    echo "  Admin Portal:  http://localhost:5001"
    echo "  Member Portal: http://localhost:5002"
    echo "  API Gateway:   http://localhost:8808"
    echo "  Grafana:       http://localhost:3300 (admin/admin)"
    echo "  PostgreSQL:    localhost:5432 (dh/dh)"
}

preflight() {
    if [[ ! -f "pg/sql/seed_data.local.sql" ]]; then
        echo "ERROR: No seed data found at pg/sql/seed_data.local.sql"
        echo "Run '$0 setup' first, or generate seed data:"
        echo "  tools/seed_data.sh generate"
        exit 1
    fi

    if ! find code -name "config.ini" -type f -print -quit | grep -q .; then
        echo "ERROR: No config.ini files found. Run '$0 setup' first."
        exit 1
    fi
}

cmd_setup() {
    echo "=== Deep Harbor Dev Environment Setup ==="
    echo ""

    # Step 1: Copy config.ini.example -> config.ini (skip if exists)
    echo "--- Copying config.ini files ---"
    local config_count=0
    local skip_count=0
    while IFS= read -r example; do
        target="${example%.example}"
        if [[ -f "$target" ]]; then
            echo "  SKIP: $target (already exists)"
            ((skip_count++)) || true
        else
            cp "$example" "$target"
            echo "  COPY: $example"
            ((config_count++)) || true
        fi
    done < <(find code -name "config.ini.example" -type f | sort)
    echo "  Copied: $config_count, Skipped: $skip_count"
    echo ""

    # Step 1b: Copy Grafana Okta env file
    echo "--- Copying Grafana Okta env file ---"
    if [[ -f ".env.grafana.okta.production" ]]; then
        echo "  SKIP: .env.grafana.okta.production (already exists)"
    else
        cp .env.grafana.okta.example .env.grafana.okta.production
        echo "  COPY: .env.grafana.okta.example -> .env.grafana.okta.production"
    fi
    echo ""

    # Step 2: Generate seed data
    echo "--- Generating seed data ---"
    if [[ -f "pg/sql/seed_data.local.sql" ]] && [[ -s "pg/sql/seed_data.local.sql" ]]; then
        echo "  Seed data already exists ($(wc -l < pg/sql/seed_data.local.sql) lines)"
        echo "  To regenerate: tools/seed_data.sh generate"
    else
        if command -v uv &> /dev/null; then
            tools/seed_data.sh generate
        else
            echo "  WARNING: uv not installed, using static seed data"
            tools/seed_data.sh static
        fi
    fi
    echo ""

    # Step 3: Build and start
    echo "--- Building and starting ---"
    cmd_start

    echo ""
    echo "=== Setup complete ==="
    echo ""
    echo "Day-to-day commands:"
    echo "  $0 start    Start the dev environment"
    echo "  $0 stop     Stop containers (database persists)"
    echo "  $0 reset    Full reset: stop, remove volumes, rebuild, start"
}

cmd_start() {
    preflight

    echo "Starting Deep Harbor dev environment..."
    $COMPOSE up --build -d

    echo ""
    echo "Dev environment started."
    print_access
}

cmd_stop() {
    echo "Stopping Deep Harbor dev environment..."
    $COMPOSE down

    echo "Dev environment stopped. Database volume preserved."
    echo "Run '$0 start' to restart (data persists)."
    echo "Run '$0 reset' for a full reset (re-seeds database)."
}

cmd_reset() {
    START_TIME=$(date +"%Y-%m-%d %H:%M:%S")
    echo "Resetting Deep Harbor dev environment. Started at: $START_TIME"

    echo "Stopping and removing volumes..."
    $COMPOSE down --volumes

    sleep 2

    echo "Rebuilding and starting..."
    cmd_start

    END_TIME=$(date +"%Y-%m-%d %H:%M:%S")
    echo ""
    echo "Reset completed. Ended at: $END_TIME"

    START_SEC=$(date -d "$START_TIME" +%s)
    END_SEC=$(date -d "$END_TIME" +%s)
    DURATION=$((END_SEC - START_SEC))
    MINUTES=$((DURATION / 60))
    SECS=$((DURATION % 60))
    echo "Total duration: $MINUTES minutes, $SECS seconds"
}

cmd_clean() {
    echo "Cleaning Deep Harbor dev environment..."

    # Stop containers and remove volumes
    $COMPOSE down --volumes 2>/dev/null || true

    # Remove all config.ini files
    local config_count
    config_count=$(find code -name "config.ini" -type f | wc -l)
    if [[ "$config_count" -gt 0 ]]; then
        find code -name "config.ini" -type f -delete
        echo "Removed $config_count config.ini files"
    fi

    # Remove generated seed data
    if [[ -f "pg/sql/seed_data.local.sql" ]]; then
        rm -f pg/sql/seed_data.local.sql
        echo "Removed pg/sql/seed_data.local.sql"
    fi

    echo ""
    echo "Clean complete. Run '$0 setup' to start fresh."
}

cmd_status() {
    $COMPOSE ps
}

# Main dispatch
case "${1:-}" in
    setup)
        cmd_setup
        ;;
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    reset)
        cmd_reset
        ;;
    clean)
        cmd_clean
        ;;
    status)
        cmd_status
        ;;
    -h|--help|help)
        usage
        ;;
    "")
        usage
        exit 1
        ;;
    *)
        echo "Unknown command: $1"
        echo ""
        usage
        exit 1
        ;;
esac
