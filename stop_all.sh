#!/bin/bash
echo "Stopping Agent System..."
for pidfile in /home/tekken/agent-system/logs/*.pid; do
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        name=$(basename "$pidfile" .pid)
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "Stopped $name (PID: $pid)"
        fi
        rm "$pidfile"
    fi
done
echo "All agents stopped."
