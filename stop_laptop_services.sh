#!/bin/bash
echo "⏹ Зупиняємо сервіси..."
[ -f /tmp/ollama_worker.pid ] && kill $(cat /tmp/ollama_worker.pid) && echo "✅ Ollama Worker зупинено"
[ -f /tmp/embedding_service.pid ] && kill $(cat /tmp/embedding_service.pid) && echo "✅ Embedding Service зупинено"
rm -f /tmp/ollama_worker.pid /tmp/embedding_service.pid
echo "Готово!"
