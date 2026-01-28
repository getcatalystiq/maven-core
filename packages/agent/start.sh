#!/bin/bash
# Start both the main Node.js server and the Bun WebSocket server

echo "[START] Starting Maven Agent servers..."

# Start Bun WebSocket server in background on port 8081
echo "[START] Starting Bun WebSocket server on port 8081..."
bun run dist/ws-server.js &
WS_PID=$!

# Give Bun a moment to start
sleep 1

# Start main Node.js server on port 8080
echo "[START] Starting main Node.js server on port 8080..."
node dist/index.js &
MAIN_PID=$!

echo "[START] Both servers started (main: $MAIN_PID, ws: $WS_PID)"

# Wait for either process to exit
wait -n

# If one dies, kill the other and exit
echo "[START] A server exited, shutting down..."
kill $WS_PID 2>/dev/null
kill $MAIN_PID 2>/dev/null
