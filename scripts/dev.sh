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

# PID file locations
PID_DIR="$PROJECT_ROOT/.pids"
CONTROL_PLANE_PID="$PID_DIR/control-plane.pid"
TENANT_WORKER_PID="$PID_DIR/tenant-worker.pid"

# Log file locations
LOG_DIR="$PROJECT_ROOT/.logs"
CONTROL_PLANE_LOG="$LOG_DIR/control-plane.log"
TENANT_WORKER_LOG="$LOG_DIR/tenant-worker.log"
AGENT_LOG="$LOG_DIR/agent.log"

# Parse command
COMMAND="${1:-start}"

mkdir -p "$PID_DIR" "$LOG_DIR"

# Function to check if a process is running
is_running() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    local pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

# Function to check if agent container is running
is_agent_running() {
  docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps --status running agent 2>/dev/null | grep -q agent
}

# Function to start a server (non-Docker)
start_server() {
  local name="$1"
  local dir="$2"
  local pid_file="$3"
  local log_file="$4"
  local port="$5"

  if is_running "$pid_file"; then
    echo -e "  ${YELLOW}⚠${NC} $name already running (PID: $(cat "$pid_file"))"
    return 0
  fi

  echo -e "  ${BLUE}→${NC} Starting $name on port $port..."

  cd "$PROJECT_ROOT/$dir"
  nohup npm run dev > "$log_file" 2>&1 &
  local pid=$!
  echo $pid > "$pid_file"

  # Wait a moment and verify it started
  sleep 2
  if is_running "$pid_file"; then
    echo -e "  ${GREEN}✓${NC} $name started (PID: $pid)"
  else
    echo -e "  ${RED}✗${NC} $name failed to start. Check $log_file"
    return 1
  fi
}

# Function to start agent via Docker
start_agent() {
  if is_agent_running; then
    echo -e "  ${YELLOW}⚠${NC} Agent already running (Docker)"
    return 0
  fi

  echo -e "  ${BLUE}→${NC} Starting Agent on port 8080 (Docker)..."

  cd "$PROJECT_ROOT"
  docker compose up -d --build agent > "$AGENT_LOG" 2>&1

  # Wait for container to be healthy
  sleep 3
  if is_agent_running; then
    echo -e "  ${GREEN}✓${NC} Agent started (Docker container)"
  else
    echo -e "  ${RED}✗${NC} Agent failed to start. Check: docker compose logs agent"
    return 1
  fi
}

# Function to stop a server (non-Docker)
stop_server() {
  local name="$1"
  local pid_file="$2"

  if ! is_running "$pid_file"; then
    echo -e "  ${YELLOW}○${NC} $name not running"
    rm -f "$pid_file"
    return 0
  fi

  local pid=$(cat "$pid_file")
  echo -e "  ${BLUE}→${NC} Stopping $name (PID: $pid)..."

  # Kill the process and its children
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true

  # Wait for it to stop
  sleep 1
  if ! is_running "$pid_file"; then
    echo -e "  ${GREEN}✓${NC} $name stopped"
    rm -f "$pid_file"
  else
    # Force kill if still running
    kill -9 "$pid" 2>/dev/null || true
    pkill -9 -P "$pid" 2>/dev/null || true
    rm -f "$pid_file"
    echo -e "  ${GREEN}✓${NC} $name force stopped"
  fi
}

# Function to stop agent Docker container
stop_agent() {
  if ! is_agent_running; then
    echo -e "  ${YELLOW}○${NC} Agent not running"
    return 0
  fi

  echo -e "  ${BLUE}→${NC} Stopping Agent (Docker)..."
  cd "$PROJECT_ROOT"
  docker compose stop agent > /dev/null 2>&1
  docker compose rm -f agent > /dev/null 2>&1
  echo -e "  ${GREEN}✓${NC} Agent stopped"
}

# Function to show status
show_status() {
  echo -e "${BLUE}Server Status${NC}"
  echo ""

  if is_running "$CONTROL_PLANE_PID"; then
    echo -e "  ${GREEN}●${NC} Control Plane  (PID: $(cat "$CONTROL_PLANE_PID")) - http://localhost:8787"
  else
    echo -e "  ${RED}○${NC} Control Plane  - not running"
  fi

  if is_running "$TENANT_WORKER_PID"; then
    echo -e "  ${GREEN}●${NC} Tenant Worker  (PID: $(cat "$TENANT_WORKER_PID")) - http://localhost:8788"
  else
    echo -e "  ${RED}○${NC} Tenant Worker  - not running"
  fi

  if is_agent_running; then
    echo -e "  ${GREEN}●${NC} Agent          (Docker) - http://localhost:8080"
  else
    echo -e "  ${RED}○${NC} Agent          - not running"
  fi

  echo ""
}

# Function to show logs
show_logs() {
  local service="${2:-all}"

  case $service in
    control-plane|cp)
      echo -e "${BLUE}Control Plane Logs${NC}"
      tail -f "$CONTROL_PLANE_LOG"
      ;;
    tenant-worker|tw)
      echo -e "${BLUE}Tenant Worker Logs${NC}"
      tail -f "$TENANT_WORKER_LOG"
      ;;
    agent|ag)
      echo -e "${BLUE}Agent Logs (Docker)${NC}"
      cd "$PROJECT_ROOT"
      docker compose logs -f agent
      ;;
    all|*)
      echo -e "${BLUE}All Logs (Ctrl+C to exit)${NC}"
      echo -e "${YELLOW}Note: Agent logs shown via Docker${NC}"
      # Start docker logs in background, tail the others
      cd "$PROJECT_ROOT"
      docker compose logs -f agent &
      DOCKER_PID=$!
      trap "kill $DOCKER_PID 2>/dev/null" EXIT
      tail -f "$CONTROL_PLANE_LOG" "$TENANT_WORKER_LOG"
      ;;
  esac
}

# Main command handler
case $COMMAND in
  start)
    echo -e "${GREEN}Maven Core - Starting Development Servers${NC}"
    echo "==========================================="
    echo ""

    start_server "Control Plane" "packages/control-plane" "$CONTROL_PLANE_PID" "$CONTROL_PLANE_LOG" "8787"
    start_server "Tenant Worker" "packages/tenant-worker" "$TENANT_WORKER_PID" "$TENANT_WORKER_LOG" "8788"
    start_agent

    echo ""
    echo -e "${GREEN}All servers started!${NC}"
    echo ""
    echo "Endpoints:"
    echo -e "  Control Plane: ${YELLOW}http://localhost:8787${NC}"
    echo -e "  Tenant Worker: ${YELLOW}http://localhost:8788${NC}"
    echo -e "  Agent:         ${YELLOW}http://localhost:8080${NC} (Docker)"
    echo ""
    echo "Commands:"
    echo -e "  ${YELLOW}npm run dev:status${NC}  - Check server status"
    echo -e "  ${YELLOW}npm run dev:logs${NC}    - View all logs"
    echo -e "  ${YELLOW}npm run dev:stop${NC}    - Stop all servers"
    ;;

  stop)
    echo -e "${GREEN}Maven Core - Stopping Development Servers${NC}"
    echo "==========================================="
    echo ""

    stop_server "Control Plane" "$CONTROL_PLANE_PID"
    stop_server "Tenant Worker" "$TENANT_WORKER_PID"
    stop_agent

    echo ""
    echo -e "${GREEN}All servers stopped.${NC}"
    ;;

  restart)
    echo -e "${GREEN}Maven Core - Restarting Development Servers${NC}"
    echo "============================================="
    echo ""

    stop_server "Control Plane" "$CONTROL_PLANE_PID"
    stop_server "Tenant Worker" "$TENANT_WORKER_PID"
    stop_agent

    echo ""
    sleep 1

    start_server "Control Plane" "packages/control-plane" "$CONTROL_PLANE_PID" "$CONTROL_PLANE_LOG" "8787"
    start_server "Tenant Worker" "packages/tenant-worker" "$TENANT_WORKER_PID" "$TENANT_WORKER_LOG" "8788"
    start_agent

    echo ""
    echo -e "${GREEN}All servers restarted!${NC}"
    ;;

  status)
    show_status
    ;;

  logs)
    show_logs "$@"
    ;;

  *)
    echo "Usage: npm run dev:[start|stop|restart|status|logs]"
    echo ""
    echo "Commands:"
    echo "  start     Start all development servers (agent runs in Docker)"
    echo "  stop      Stop all development servers"
    echo "  restart   Restart all development servers"
    echo "  status    Show server status"
    echo "  logs      Tail logs (all, control-plane, tenant-worker, agent)"
    exit 1
    ;;
esac
