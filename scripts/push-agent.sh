#!/bin/bash
set -e

# Configuration
ACCOUNT_ID="${CF_ACCOUNT_ID:-}"
IMAGE_NAME="maven-agent"
REGISTRY="registry.cloudflare.com"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse arguments
TAG="${1:-latest}"

echo -e "${GREEN}Maven Agent - Push to Cloudflare Registry${NC}"
echo "==========================================="

# Check for account ID
if [ -z "$ACCOUNT_ID" ]; then
  # Try to get from wrangler
  ACCOUNT_ID=$(cd "$PROJECT_ROOT/packages/control-plane" && npx wrangler whoami 2>/dev/null | grep -oE '[a-f0-9]{32}' | head -1 || true)

  if [ -z "$ACCOUNT_ID" ]; then
    echo -e "${RED}Error: CF_ACCOUNT_ID not set and couldn't detect from wrangler${NC}"
    echo "Set it with: export CF_ACCOUNT_ID=your-account-id"
    exit 1
  fi
fi

echo -e "Account ID: ${YELLOW}${ACCOUNT_ID}${NC}"
echo -e "Image tag:  ${YELLOW}${TAG}${NC}"
echo ""

# Full image path
FULL_IMAGE="${REGISTRY}/${ACCOUNT_ID}/${IMAGE_NAME}:${TAG}"

# Step 1: Build the image
echo -e "${GREEN}[1/3] Building Docker image...${NC}"
cd "$PROJECT_ROOT"
# Build for linux/amd64 - required for Cloudflare sandbox base image
docker build --platform linux/amd64 -t "${IMAGE_NAME}:${TAG}" -f packages/agent/Dockerfile .

# Step 2: Tag for Cloudflare registry
echo -e "${GREEN}[2/3] Tagging image...${NC}"
docker tag "${IMAGE_NAME}:${TAG}" "${FULL_IMAGE}"

# Step 3: Push to registry using wrangler (handles auth automatically)
echo -e "${GREEN}[3/3] Pushing to Cloudflare registry...${NC}"
echo -e "Pushing to: ${YELLOW}${FULL_IMAGE}${NC}"

# Use wrangler containers push which handles authentication
npx wrangler containers push "${IMAGE_NAME}:${TAG}"

echo ""
echo -e "${GREEN}Done!${NC}"
echo -e "Image pushed to: ${YELLOW}${FULL_IMAGE}${NC}"
echo ""
echo "To verify:"
echo -e "  ${YELLOW}npx wrangler containers images list${NC}"
