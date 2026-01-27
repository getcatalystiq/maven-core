# Use Cloudflare Sandbox base image - required for Sandbox SDK compatibility
FROM docker.io/cloudflare/sandbox:0.7.0

# The Cloudflare Sandbox image includes:
# - Ubuntu Linux with Node.js, Python, Git
# - Internal Sandbox SDK daemon for handling SDK requests

WORKDIR /app

# Install Bun (Anthropic owns Bun, Claude SDK is designed for it)
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:$PATH"

# Install Claude CLI globally (pin to version with license agreement fix)
# See: https://github.com/anthropics/claude-code/issues/17373
RUN npm install -g @anthropic-ai/claude-code@latest

# Copy monorepo package files for workspace resolution
COPY package*.json ./
COPY bun.lockb* ./
COPY packages/shared/package.json ./packages/shared/
COPY packages/agent/package.json ./packages/agent/

# Install all dependencies with Bun
RUN bun install --frozen-lockfile || bun install

# Copy shared package source and build
COPY packages/shared ./packages/shared
RUN cd packages/shared && bun run build

# Copy agent package source and build
COPY packages/agent ./packages/agent
RUN cd packages/agent && bun run build

# Create a non-root user for running the agent
# This is required because Claude CLI refuses --dangerously-skip-permissions when running as root
RUN useradd -m -s /bin/bash maven && \
    chown -R maven:maven /app && \
    mkdir -p /home/maven/.claude && \
    chown -R maven:maven /home/maven/.claude && \
    mkdir -p /home/maven/.bun && \
    chown -R maven:maven /home/maven/.bun

# Copy Bun to user location so maven user can run it
RUN cp -r /root/.bun /home/maven/.bun && \
    chown -R maven:maven /home/maven/.bun

WORKDIR /app/packages/agent

# Switch to non-root user
USER maven

# Set PATH for maven user
ENV PATH="/home/maven/.bun/bin:$PATH"

# Expose port for development
EXPOSE 8080

ENV PORT=8080
ENV NODE_ENV=production
ENV HOME=/home/maven
