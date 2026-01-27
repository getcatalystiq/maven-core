#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse arguments
EMAIL="$1"
PASSWORD="$2"
TARGET="${3:---local}"

if [ -z "$EMAIL" ] || [ -z "$PASSWORD" ]; then
  echo -e "${RED}Usage: npm run create-super-admin <email> <password> [--local|--remote]${NC}"
  echo ""
  echo "Creates a super-admin user that can manage all tenants."
  echo "Super-admins have no tenant (tenant_id is NULL)."
  echo ""
  echo "Arguments:"
  echo "  email       Email address for the super-admin"
  echo "  password    Password (min 8 chars, must include uppercase, lowercase, number, special char)"
  echo "  --local     Create in local D1 (default)"
  echo "  --remote    Create in production D1"
  exit 1
fi

# Validate password strength
if [ ${#PASSWORD} -lt 8 ]; then
  echo -e "${RED}Error: Password must be at least 8 characters${NC}"
  exit 1
fi

echo -e "${GREEN}Maven Core - Create Super Admin${NC}"
echo "================================="
echo ""
echo -e "Email: ${YELLOW}$EMAIL${NC}"
echo -e "Target: ${YELLOW}$TARGET${NC}"
echo ""

cd "$PROJECT_ROOT"

# Generate UUID
USER_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Hash password using the shared library (same format as app)
echo -e "Hashing password..."
PASSWORD_HASH=$(npx tsx "$SCRIPT_DIR/hash-password.ts" "$PASSWORD" 2>/dev/null)

if [ -z "$PASSWORD_HASH" ]; then
  echo -e "${RED}Error: Failed to hash password${NC}"
  exit 1
fi

cd "$PROJECT_ROOT/packages/control-plane"

# Check if user already exists (tenant-less super-admin)
echo -e "Checking if user exists..."
EXISTING=$(npx wrangler d1 execute maven $TARGET --command="SELECT id FROM users WHERE email = '$EMAIL' AND tenant_id IS NULL;" 2>/dev/null | grep -c "id" || true)

if [ "$EXISTING" != "0" ]; then
  echo -e "${YELLOW}User already exists. Updating password...${NC}"
  npx wrangler d1 execute maven $TARGET --command="UPDATE users SET password_hash = '$PASSWORD_HASH', updated_at = datetime('now') WHERE email = '$EMAIL' AND tenant_id IS NULL;" 2>/dev/null
  echo -e "${GREEN}Password updated successfully!${NC}"
  exit 0
fi

# Create super-admin user with NULL tenant_id
echo -e "Creating super-admin user..."
npx wrangler d1 execute maven $TARGET --command="INSERT INTO users (id, email, tenant_id, roles, password_hash, enabled, created_at, updated_at) VALUES ('$USER_ID', '$EMAIL', NULL, '[\"super-admin\"]', '$PASSWORD_HASH', 1, datetime('now'), datetime('now'));" 2>/dev/null

if [ $? -eq 0 ]; then
  echo ""
  echo -e "${GREEN}Super-admin created successfully!${NC}"
  echo ""
  echo -e "User ID: ${YELLOW}$USER_ID${NC}"
  echo -e "Email: ${YELLOW}$EMAIL${NC}"
  echo -e "Tenant: ${YELLOW}(none - global super-admin)${NC}"
  echo -e "Roles: ${YELLOW}[\"super-admin\"]${NC}"
  echo ""
  echo "Login with:"
  echo -e "  curl -X POST http://localhost:8787/auth/login \\"
  echo -e "    -H \"Content-Type: application/json\" \\"
  echo -e "    -d '{\"email\":\"$EMAIL\",\"password\":\"<password>\"}'"
else
  echo -e "${RED}Failed to create super-admin${NC}"
  exit 1
fi
