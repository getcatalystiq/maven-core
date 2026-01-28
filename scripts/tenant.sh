#!/bin/bash
set -e

# Tenant Worker CLI - Manage tenant-specific deployments
#
# Usage:
#   npm run tenant dev <slug>      # Local dev with tenant config
#   npm run tenant deploy <slug>   # Deploy dedicated tenant worker
#   npm run tenant list            # List all tenants

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TENANT_WORKER_DIR="$PROJECT_ROOT/packages/tenant-worker"
CONFIG_CACHE_DIR="$TENANT_WORKER_DIR/.tenant-config"

# Control plane URL (configurable via env)
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://localhost:8787}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-}"

# Container image settings
CF_ACCOUNT_ID="${CF_ACCOUNT_ID:?Error: CF_ACCOUNT_ID environment variable is required}"
AGENT_IMAGE_TAG="${AGENT_IMAGE_TAG:-v1.0.0}"

# Parse command and arguments
COMMAND="${1:-help}"
SLUG="${2:-}"

mkdir -p "$CONFIG_CACHE_DIR"

# Function to fetch tenant config from control plane
fetch_tenant_config() {
  local slug="$1"
  local cache_file="$CONFIG_CACHE_DIR/$slug.json"

  echo -e "  ${BLUE}→${NC} Fetching config for tenant: $slug"

  # Build curl headers
  local headers=(-H "Content-Type: application/json")
  if [ -n "$INTERNAL_API_KEY" ]; then
    headers+=(-H "X-Internal-Key: $INTERNAL_API_KEY")
  fi

  # Try to fetch from control plane
  local response
  response=$(curl -s -w "\n%{http_code}" "${headers[@]}" "$CONTROL_PLANE_URL/internal/tenant/$slug" 2>/dev/null) || true

  local http_code=$(echo "$response" | tail -n1)
  local body=$(echo "$response" | sed '$d')

  if [ "$http_code" = "200" ]; then
    echo "$body" > "$cache_file"
    echo -e "  ${GREEN}✓${NC} Config fetched and cached"
    return 0
  elif [ -f "$cache_file" ]; then
    echo -e "  ${YELLOW}⚠${NC} Could not reach control plane (HTTP $http_code), using cached config"
    return 0
  else
    echo -e "  ${RED}✗${NC} Failed to fetch config (HTTP $http_code) and no cache available"
    echo -e "  ${YELLOW}Hint:${NC} Make sure control plane is running: npm run dev:start"
    return 1
  fi
}

# Function to read tenant config from cache
read_tenant_config() {
  local slug="$1"
  local cache_file="$CONFIG_CACHE_DIR/$slug.json"

  if [ ! -f "$cache_file" ]; then
    echo ""
    return 1
  fi

  cat "$cache_file"
}

# Function to extract value from JSON (portable, no jq dependency)
json_value() {
  local json="$1"
  local key="$2"
  echo "$json" | grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*: *"\([^"]*\)".*/\1/'
}

# Function to generate wrangler config with injected container
generate_wrangler_config() {
  local slug="$1"
  # Put generated config in tenant-worker dir so wrangler can find src/index.ts
  local output_file="$TENANT_WORKER_DIR/wrangler-$slug.toml"
  local base_config="$TENANT_WORKER_DIR/wrangler.toml"

  # Read base config and inject container config before first "# R2 bucket for agent logs"
  awk -v slug="$slug" -v account="$CF_ACCOUNT_ID" -v tag="$AGENT_IMAGE_TAG" '
    BEGIN { injected = 0 }
    /^# R2 bucket for agent logs/ && !injected {
      print "[[containers]]"
      print "name = \"maven-tenant-" slug "-sandbox\""
      print "class_name = \"Sandbox\""
      print "image = \"registry.cloudflare.com/" account "/maven-agent:" tag "\""
      print "instance_type = \"basic\""
      print ""
      injected = 1
    }
    { print }
  ' "$base_config" > "$output_file"

  echo "$output_file"
}

# Function to list tenants
list_tenants() {
  echo -e "${BLUE}Fetching tenants from Control Plane...${NC}"
  echo ""

  local headers=(-H "Content-Type: application/json")
  if [ -n "$INTERNAL_API_KEY" ]; then
    headers+=(-H "X-Internal-Key: $INTERNAL_API_KEY")
  fi

  local response
  response=$(curl -s "${headers[@]}" "$CONTROL_PLANE_URL/internal/tenants" 2>/dev/null) || true

  if [ -z "$response" ]; then
    echo -e "${RED}Could not reach control plane at $CONTROL_PLANE_URL${NC}"
    echo ""
    echo "Make sure control plane is running:"
    echo -e "  ${YELLOW}npm run dev:start${NC}"
    echo ""

    # Show cached tenants if available
    if [ -d "$CONFIG_CACHE_DIR" ] && [ "$(ls -A "$CONFIG_CACHE_DIR" 2>/dev/null)" ]; then
      echo -e "${BLUE}Cached tenants:${NC}"
      for f in "$CONFIG_CACHE_DIR"/*.json; do
        [ -f "$f" ] || continue
        local slug=$(basename "$f" .json)
        local config=$(cat "$f")
        local name=$(json_value "$config" "name")
        local tier=$(json_value "$config" "tier")
        echo -e "  ${GREEN}●${NC} $slug ($name) - $tier"
      done
    fi
    return 1
  fi

  # Parse and display tenants
  # Simple parsing without jq
  echo -e "${GREEN}Available Tenants:${NC}"
  echo ""
  echo "$response" | grep -o '"slug":"[^"]*"' | sed 's/"slug":"//;s/"$//' | while read -r slug; do
    echo -e "  ${GREEN}●${NC} $slug"
  done
  echo ""
}

# Function to run tenant dev server
run_dev() {
  local slug="$1"

  if [ -z "$slug" ]; then
    echo -e "${RED}Error: tenant slug required${NC}"
    echo ""
    echo "Usage: npm run tenant dev <slug>"
    echo "Example: npm run tenant dev my-tenant"
    exit 1
  fi

  echo -e "${GREEN}Maven Tenant Worker - Development Mode${NC}"
  echo "========================================"
  echo ""

  # Fetch/update config
  if ! fetch_tenant_config "$slug"; then
    exit 1
  fi

  # Read config
  local config
  config=$(read_tenant_config "$slug")
  if [ -z "$config" ]; then
    echo -e "${RED}Error: Could not read config for tenant: $slug${NC}"
    exit 1
  fi

  # Extract values
  local tenant_id=$(json_value "$config" "id")
  local tenant_slug=$(json_value "$config" "slug")
  local tenant_name=$(json_value "$config" "name")
  local tenant_tier=$(json_value "$config" "tier")

  echo -e "  Tenant: ${YELLOW}$tenant_name${NC} ($tenant_slug)"
  echo -e "  Tier:   ${YELLOW}$tenant_tier${NC}"
  echo -e "  ID:     ${YELLOW}$tenant_id${NC}"
  echo ""

  # Run wrangler with injected vars
  cd "$TENANT_WORKER_DIR"

  echo -e "${BLUE}Starting wrangler dev...${NC}"
  echo ""

  exec wrangler dev \
    --name "maven-tenant-$tenant_slug" \
    --var "TENANT_ID:$tenant_id" \
    --var "TENANT_SLUG:$tenant_slug"
}

# Function to deploy tenant worker
run_deploy() {
  local slug="$1"
  local dry_run="${2:-}"

  if [ -z "$slug" ]; then
    echo -e "${RED}Error: tenant slug required${NC}"
    echo ""
    echo "Usage: npm run tenant deploy <slug>"
    echo "Example: npm run tenant deploy my-tenant"
    exit 1
  fi

  echo -e "${GREEN}Maven Tenant Worker - Deploy${NC}"
  echo "=============================="
  echo ""

  # Fetch/update config
  if ! fetch_tenant_config "$slug"; then
    exit 1
  fi

  # Read config
  local config
  config=$(read_tenant_config "$slug")
  if [ -z "$config" ]; then
    echo -e "${RED}Error: Could not read config for tenant: $slug${NC}"
    exit 1
  fi

  # Extract values
  local tenant_id=$(json_value "$config" "id")
  local tenant_slug=$(json_value "$config" "slug")
  local tenant_name=$(json_value "$config" "name")
  local tenant_tier=$(json_value "$config" "tier")

  echo -e "  Tenant: ${YELLOW}$tenant_name${NC} ($tenant_slug)"
  echo -e "  Tier:   ${YELLOW}$tenant_tier${NC}"
  echo -e "  ID:     ${YELLOW}$tenant_id${NC}"
  echo -e "  Image:  ${YELLOW}maven-agent:${AGENT_IMAGE_TAG}${NC}"
  echo ""

  # Generate wrangler config with container injected
  echo -e "  ${BLUE}→${NC} Generating wrangler config..."
  local wrangler_config
  wrangler_config=$(generate_wrangler_config "$tenant_slug")
  echo -e "  ${GREEN}✓${NC} Config generated: $(basename "$wrangler_config")"
  echo ""

  cd "$TENANT_WORKER_DIR"

  if [ "$dry_run" = "--dry-run" ]; then
    echo -e "${YELLOW}Dry run - would deploy with:${NC}"
    echo ""
    echo "  wrangler deploy \\"
    echo "    --config $wrangler_config \\"
    echo "    --name maven-tenant-$tenant_slug \\"
    echo "    --var TENANT_ID:$tenant_id \\"
    echo "    --var TENANT_SLUG:$tenant_slug \\"
    echo "    --env \"\""
    echo ""
    echo -e "${BLUE}Generated container config:${NC}"
    grep -A4 "^\[\[containers\]\]" "$wrangler_config" || true
    echo ""
    return 0
  fi

  echo -e "${BLUE}Deploying to Cloudflare...${NC}"
  echo ""

  exec wrangler deploy \
    --config "$wrangler_config" \
    --name "maven-tenant-$tenant_slug" \
    --var "TENANT_ID:$tenant_id" \
    --var "TENANT_SLUG:$tenant_slug" \
    --env ""
}

# Main command handler
case $COMMAND in
  dev)
    run_dev "$SLUG"
    ;;

  deploy)
    run_deploy "$SLUG" "$3"
    ;;

  list)
    list_tenants
    ;;

  help|*)
    echo -e "${BLUE}Maven Tenant Worker CLI${NC}"
    echo ""
    echo "Usage: npm run tenant <command> [args]"
    echo ""
    echo "Commands:"
    echo -e "  ${GREEN}dev <slug>${NC}       Start local dev server for a tenant"
    echo -e "  ${GREEN}deploy <slug>${NC}    Deploy dedicated worker for a tenant"
    echo -e "  ${GREEN}list${NC}             List all available tenants"
    echo ""
    echo "Examples:"
    echo -e "  ${YELLOW}npm run tenant dev my-tenant${NC}"
    echo -e "  ${YELLOW}npm run tenant deploy my-tenant${NC}"
    echo -e "  ${YELLOW}npm run tenant deploy my-tenant --dry-run${NC}"
    echo -e "  ${YELLOW}npm run tenant list${NC}"
    echo ""
    echo "Environment variables:"
    echo -e "  ${YELLOW}CONTROL_PLANE_URL${NC}  Control plane URL (default: http://localhost:8787)"
    echo -e "  ${YELLOW}INTERNAL_API_KEY${NC}   API key for internal endpoints"
    echo -e "  ${YELLOW}CF_ACCOUNT_ID${NC}      Cloudflare account ID"
    echo -e "  ${YELLOW}AGENT_IMAGE_TAG${NC}    Agent container image tag (default: v1.0.0)"
    echo ""

    if [ "$COMMAND" != "help" ]; then
      exit 1
    fi
    ;;
esac
