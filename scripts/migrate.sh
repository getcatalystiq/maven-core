#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MIGRATIONS_DIR="$PROJECT_ROOT/packages/control-plane/migrations"

# Parse arguments
TARGET="--local"
DB_NAME="maven"
COMMAND="up"

while [[ $# -gt 0 ]]; do
  case $1 in
    --remote)
      TARGET="--remote"
      shift
      ;;
    --local)
      TARGET="--local"
      shift
      ;;
    --db)
      DB_NAME="$2"
      shift 2
      ;;
    status|up|create)
      COMMAND="$1"
      shift
      ;;
    *)
      # For create command, capture the name
      if [ "$COMMAND" = "create" ]; then
        MIGRATION_NAME="$1"
      fi
      shift
      ;;
  esac
done

cd "$PROJECT_ROOT/packages/control-plane"

echo -e "${GREEN}Maven Core - Database Migrations${NC}"
echo "=================================="
echo -e "Target: ${YELLOW}$TARGET${NC}"
echo -e "Database: ${YELLOW}$DB_NAME${NC}"
echo ""

# Function to run SQL via wrangler
run_sql() {
  local sql="$1"
  npx wrangler d1 execute "$DB_NAME" $TARGET --command="$sql" 2>/dev/null
}

# Function to run SQL file via wrangler
run_sql_file() {
  local file="$1"
  npx wrangler d1 execute "$DB_NAME" $TARGET --file="$file" 2>/dev/null
}

# Function to check if migrations table exists and create it
ensure_migrations_table() {
  run_sql "CREATE TABLE IF NOT EXISTS _migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
  );" > /dev/null 2>&1 || true
}

# Function to get applied migrations (parses JSON output from wrangler)
get_applied_migrations() {
  run_sql "SELECT name FROM _migrations ORDER BY id;" 2>/dev/null | \
    grep -o '"name": *"[^"]*"' | \
    sed 's/"name": *"\([^"]*\)"/\1/' || true
}

# Function to check if migration was applied
is_migration_applied() {
  local name="$1"
  local result=$(run_sql "SELECT COUNT(*) as count FROM _migrations WHERE name = '$name';" 2>/dev/null | grep -E '^[0-9]+$' | head -1)
  [ "$result" = "1" ]
}

# Function to mark migration as applied
mark_migration_applied() {
  local name="$1"
  run_sql "INSERT INTO _migrations (name) VALUES ('$name');" > /dev/null 2>&1
}

# Function to get pending migrations
get_pending_migrations() {
  local applied=$(get_applied_migrations)

  for file in "$MIGRATIONS_DIR"/*.sql; do
    if [ -f "$file" ]; then
      local name=$(basename "$file" .sql)
      if ! echo "$applied" | grep -q "^$name$"; then
        echo "$name"
      fi
    fi
  done | sort
}

# Command: status
cmd_status() {
  echo -e "${BLUE}Migration Status${NC}"
  echo ""

  ensure_migrations_table

  local applied=$(get_applied_migrations)
  local has_pending=false

  for file in "$MIGRATIONS_DIR"/*.sql; do
    if [ -f "$file" ]; then
      local name=$(basename "$file" .sql)
      if echo "$applied" | grep -q "^$name$"; then
        echo -e "  ${GREEN}✓${NC} $name"
      else
        echo -e "  ${YELLOW}○${NC} $name ${YELLOW}(pending)${NC}"
        has_pending=true
      fi
    fi
  done

  echo ""
  if [ "$has_pending" = true ]; then
    echo -e "Run ${YELLOW}npm run migrate${NC} to apply pending migrations."
  else
    echo -e "${GREEN}All migrations applied.${NC}"
  fi
}

# Command: up
cmd_up() {
  echo -e "${BLUE}Running Migrations${NC}"
  echo ""

  ensure_migrations_table

  local pending=$(get_pending_migrations)

  if [ -z "$pending" ]; then
    echo -e "${GREEN}No pending migrations.${NC}"
    return 0
  fi

  local count=0
  for name in $pending; do
    local file="$MIGRATIONS_DIR/$name.sql"

    if [ -f "$file" ]; then
      echo -e "  ${BLUE}→${NC} Applying $name..."

      if run_sql_file "$file"; then
        mark_migration_applied "$name"
        echo -e "  ${GREEN}✓${NC} $name applied"
        ((count++))
      else
        echo -e "  ${RED}✗${NC} $name failed"
        exit 1
      fi
    fi
  done

  echo ""
  echo -e "${GREEN}Applied $count migration(s).${NC}"
}

# Command: create
cmd_create() {
  if [ -z "$MIGRATION_NAME" ]; then
    echo -e "${RED}Error: Migration name required${NC}"
    echo "Usage: npm run migrate:create <name>"
    echo "Example: npm run migrate:create add_audit_logs"
    exit 1
  fi

  # Generate timestamp
  local timestamp=$(date +%Y%m%d%H%M%S)
  local filename="${timestamp}_${MIGRATION_NAME}.sql"
  local filepath="$MIGRATIONS_DIR/$filename"

  # Create migration file
  cat > "$filepath" << EOF
-- Migration: $MIGRATION_NAME
-- Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")

-- Write your migration SQL here

-- Example:
-- CREATE TABLE IF NOT EXISTS example (
--   id TEXT PRIMARY KEY,
--   name TEXT NOT NULL,
--   created_at TEXT NOT NULL DEFAULT (datetime('now'))
-- );

EOF

  echo -e "${GREEN}Created migration:${NC} $filename"
  echo -e "Edit: ${YELLOW}packages/control-plane/migrations/$filename${NC}"
}

# Run command
case $COMMAND in
  status)
    cmd_status
    ;;
  up)
    cmd_up
    ;;
  create)
    cmd_create
    ;;
  *)
    echo "Usage: npm run migrate [status|up|create] [--local|--remote]"
    echo ""
    echo "Commands:"
    echo "  status              Show migration status"
    echo "  up                  Apply pending migrations (default)"
    echo "  create <name>       Create a new migration file"
    echo ""
    echo "Options:"
    echo "  --local             Run against local D1 (default)"
    echo "  --remote            Run against remote D1"
    echo "  --db <name>         Database name (default: maven)"
    exit 1
    ;;
esac
