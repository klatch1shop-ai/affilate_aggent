#!/bin/bash
# ═══════════════════════════════════════════════════
# ЗАПУСК СЕРВІСІВ НОУТБУКА — виконувати після кожного перезавантаження
# ═══════════════════════════════════════════════════

cd ~/agent-system
source venv/bin/activate

echo "🚀 Запускаємо сервіси ноутбука..."

# 1. Ollama (якщо не запущений)
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "▶ Ollama не запущений — стартуємо..."
    OLLAMA_HOST=0.0.0.0:11434 ollama serve &
    sleep 3
else
    echo "✅ Ollama вже запущений"
fi

# 2. Ollama Worker (обробляє queue:ollama з сервера)
echo "▶ Запускаємо Ollama Worker..."
nohup python3 shared/utils/ollama_worker.py > /tmp/ollama_worker.log 2>&1 &
WORKER_PID=$!
echo "✅ Ollama Worker PID=$WORKER_PID"

# 3. Embedding Service (обробляє queue:embeddings з сервера)
echo "▶ Запускаємо Embedding Service..."
nohup python3 embedding_service.py > /tmp/embedding_service.log 2>&1 &
EMBED_PID=$!
echo "✅ Embedding Service PID=$EMBED_PID"

# Зберігаємо PID для зупинки
echo $WORKER_PID > /tmp/ollama_worker.pid
echo $EMBED_PID > /tmp/embedding_service.pid

echo ""
echo "═══════════════════════════════"
echo "✅ Всі сервіси запущені!"
echo "   Ollama Worker:     /tmp/ollama_worker.log"
echo "   Embedding Service: /tmp/embedding_service.log"
echo ""
echo "Для зупинки: bash ~/agent-system/stop_laptop_services.sh"
echo "═══════════════════════════════"

# Слідкуємо за логами
tail -f /tmp/ollama_worker.log /tmp/embedding_service.log
