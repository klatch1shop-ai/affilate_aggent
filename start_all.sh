#!/bin/bash
cd /home/tek/agent-system
source venv/bin/activate
export $(grep -v "^#" .env | xargs)

echo "Starting Agent System..."
echo "Skills indexer skipped on server"
echo "Skills indexed"

# Запустити оркестратор
nohup python3 orchestrator/orchestrator.py --listen > logs/orchestrator.log 2>&1 &
echo $! > logs/orchestrator.pid
echo "Orchestrator started (PID: $(cat logs/orchestrator.pid))"

# Запустити Telegram бот
nohup python3 orchestrator/telegram_bot.py > logs/telegram_bot.log 2>&1 &
echo $! > logs/telegram_bot.pid
echo "Telegram bot started (PID: $(cat logs/telegram_bot.pid))"

# Запустити marketing агент
nohup python3 agents/marketing/marketing_agent.py --listen > logs/marketing.log 2>&1 &
echo $! > logs/marketing.pid
echo "Marketing agent started"

# Запустити finance агент
nohup python3 agents/finance/finance_agent.py --listen > logs/finance.log 2>&1 &
echo $! > logs/finance.pid
echo "Finance agent started"

# Запустити efficiency агент
nohup python3 agents/efficiency/efficiency_agent.py --listen > logs/efficiency.log 2>&1 &
echo $! > logs/efficiency.pid
echo "Efficiency agent started"

echo ""
nohup python3 agents/dev/dev_agent.py --listen > logs/developer.log 2>&1 &
echo $! > logs/developer.pid
echo "Developer agent started"
nohup python3 agents/checker/acceptance_checker.py --listen > logs/checker.log 2>&1 &
echo $! > logs/checker.pid
echo "Checker agent started"
nohup python3 shared/utils/ollama_worker.py > logs/ollama_worker.log 2>&1 &
echo $! > logs/ollama_worker.pid
echo "Ollama worker started"
echo "All agents started!"
echo "Telegram bot: @agent_system_TEKKEN_bot"

nohup python3 dashboard/api.py > logs/dashboard.log 2>&1 &
echo $! > logs/dashboard.pid
echo "Dashboard started"
