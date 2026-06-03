#!/usr/bin/env bash
#
# seed_data.sh — Manage seed data for the Deep Harbor dev environment
#
# This script provides a convenient way to use either the hand-crafted
# static seed data or the Python generator to create pg/sql/seed_data.sql.
#
# Files (matching the repo's config.ini.example → config.ini pattern):
#   pg/sql/seed_data.sql.example  — committed template (hand-crafted reference)
#   pg/sql/seed_data.sql          — gitignored working copy; Docker mounts this
#
# Usage:
#   tools/seed_data.sh static          Copy the template over the working copy
#   tools/seed_data.sh generate        Generate random seed data (26 members by default)
#   tools/seed_data.sh generate 100    Generate 111 members (100 random + 11 dev users)
#   tools/seed_data.sh generate 50 abc Generate with specific seed for reproducibility
#   tools/seed_data.sh status          Show what's currently in the working copy
#
# These commands only touch the file. To apply changes to the running DB
# you need to reset (dh_dev.sh reset), because PostgreSQL only runs
# /docker-entrypoint-initdb.d scripts on an empty volume.
#

set -euo pipefail

# Figure out the repo root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SEED_DATA_FILE="$REPO_ROOT/pg/sql/seed_data.sql"
STATIC_SOURCE="$REPO_ROOT/pg/sql/seed_data.sql.example"
GENERATOR="$REPO_ROOT/pg/tools/generate_seed_data.py"

usage() {
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  static              Copy the hand-crafted template (seed_data.sql.example)"
    echo "                      over the working copy (seed_data.sql)"
    echo "  generate [N] [SEED] Generate seed data with N random members (default: 15)"
    echo "                      plus 10 dev bypass users. Optionally specify a seed"
    echo "                      for reproducibility."
    echo "  status              Show what's currently in the working copy"
    echo ""
    echo "Examples:"
    echo "  $0 static                  Restore the hand-crafted template"
    echo "  $0 generate                Generate 25 members (15 random + 10 dev)"
    echo "  $0 generate 100            Generate 110 members (100 random + 10 dev)"
    echo "  $0 generate 50 myseed123   Reproducible: same seed = same output"
    echo "  $0 status                  Check current working copy"
    echo ""
    echo "These commands only update the file. To apply to the running DB:"
    echo "  ./dh_dev.sh reset"
}

cmd_static() {
    if [[ -f "$STATIC_SOURCE" ]]; then
        cp "$STATIC_SOURCE" "$SEED_DATA_FILE"
        local count
        count=$(grep -c "INSERT INTO member " "$SEED_DATA_FILE" || true)
        echo "Copied template: $count member inserts"
        echo "  From: $STATIC_SOURCE"
        echo "  To:   $SEED_DATA_FILE"
        echo ""
        echo "Run './dh_dev.sh reset' to apply this to the running DB."
    else
        echo "Error: Template not found at $STATIC_SOURCE"
        exit 1
    fi
}

cmd_generate() {
    local count="${1:-15}"
    local seed="${2:-}"

    if ! command -v uv &> /dev/null; then
        echo "Error: uv is required to run the generator. Install it:"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    local seed_args=()
    if [[ -n "$seed" ]]; then
        seed_args=(--seed "$seed")
    fi

    echo "Generating seed data: $count random + 11 dev users = $((count + 11)) total..."
    uv run "$GENERATOR" --count "$count" "${seed_args[@]}" --output "$SEED_DATA_FILE"
    echo "Wrote $SEED_DATA_FILE"
    echo ""
    echo "Run './dh_dev.sh reset' to apply this to the running DB."
}

cmd_status() {
    if [[ ! -f "$SEED_DATA_FILE" ]]; then
        echo "No working copy found at $SEED_DATA_FILE"
        echo "Run '$0 static' or '$0 generate' to create one."
        exit 0
    fi

    local member_count role_count
    member_count=$(grep -c "INSERT INTO member (" "$SEED_DATA_FILE" || true)
    role_count=$(grep -c "INSERT INTO member_to_role" "$SEED_DATA_FILE" || true)

    echo "Working copy: $SEED_DATA_FILE"
    echo "  Members: $member_count"
    echo "  Role assignments: $role_count"

    # Check if it's generated or static
    if head -5 "$SEED_DATA_FILE" | grep -q "generated"; then
        local seed_line
        seed_line=$(grep "Seed:" "$SEED_DATA_FILE" | head -1 || true)
        echo "  Type: Generated"
        echo "  $seed_line"
    else
        echo "  Type: Static (hand-crafted)"
    fi

    # Drift check against the committed template. Useful for static
    # working copies (tells you whether someone's hand-edited the file);
    # less meaningful for generated copies, which are expected to differ.
    if [[ -f "$STATIC_SOURCE" ]]; then
        if cmp -s "$SEED_DATA_FILE" "$STATIC_SOURCE"; then
            echo "  Matches template: yes"
        else
            echo "  Matches template: no (use '$0 static' to restore)"
        fi
    fi
}

# Main dispatch
case "${1:-}" in
    static)
        cmd_static
        ;;
    generate)
        cmd_generate "${2:-15}" "${3:-}"
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
