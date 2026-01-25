# Use Cloudflare Sandbox base image - required for Sandbox SDK compatibility
FROM docker.io/cloudflare/sandbox:0.7.0

# The Cloudflare Sandbox image includes:
# - Ubuntu Linux with Node.js, Python, Git
# - Internal Sandbox SDK daemon for handling SDK requests

WORKDIR /app

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Copy monorepo package files for workspace resolution
COPY package*.json ./
COPY packages/shared/package.json ./packages/shared/
COPY packages/agent/package.json ./packages/agent/

# Install all dependencies
RUN npm ci

# Copy shared package source and build
COPY packages/shared ./packages/shared
RUN npm run build --workspace=@maven/shared

# Copy agent package source and build
COPY packages/agent ./packages/agent
RUN npm run build --workspace=@maven/agent

# Create a non-root user for running the agent
# This is required because Claude CLI refuses --dangerously-skip-permissions when running as root
RUN useradd -m -s /bin/bash maven && \
    chown -R maven:maven /app

WORKDIR /app/packages/agent

# Switch to non-root user
USER maven

# Expose port for development
EXPOSE 8080

ENV PORT=8080
ENV NODE_ENV=production
