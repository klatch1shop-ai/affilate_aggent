#!/bin/bash
echo "=== Agent System Status ==="
echo ""
for pidfile in /home/tekken/agent-system/logs/*.pid; do
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        name=$(basename "$pidfile" .pid)
        if kill -0 "$pid" 2>/dev/null; then
            echo "  RUNNING  $name (PID: $pid)"
        else
            echo "  STOPPED  $name"
        fi
    fi
done
echo ""
echo "=== Docker Services ==="
docker compose ps --format "table {{.Name}}\t{{.Status}}"
