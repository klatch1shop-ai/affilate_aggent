"""
tg_dispatcher/ai_brain/voice_handler.py
==========================================
Локальний Speech-to-Text через faster-whisper.

На RTX 4050 (6GB VRAM):
- модель "small" (~400MB) — ідеальна якість для української
- compute_type="float16" на GPU або "int8" на CPU
- Час: ~1-3с на повідомлення після прогріву

Встановлення:
    pip install faster-whisper
    sudo apt install ffmpeg -y
"""

import os, asyncio, logging
logger = logging.getLogger(__name__)

# Визначаємо чи є CUDA
try:
    import torch
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
    COMPUTE = 'float16' if DEVICE == 'cuda' else 'int8'
except ImportError:
    DEVICE = 'cpu'
    COMPUTE = 'int8'

MODEL_SIZE = 'small'  # small = ~400MB, добра якість украунської
_model = None


def get_model():
    """Завантажує модель один раз при старті."""
    global _model
    if _model is None:
        logger.info(f'Завантаження Whisper {MODEL_SIZE} ({DEVICE}/{COMPUTE})...')
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE)
        logger.info('Whisper завантажено ✅')
    return _model


def _transcribe_sync(file_path: str) -> str:
    """Синхронна транскрибація (запускається в окремому потоці)."""
    try:
        model = get_model()
        segments, info = model.transcribe(
            file_path,
            beam_size=5,
            language='uk',           # Українська
            vad_filter=True,         # Фільтрація тиші
            vad_parameters={
                'min_silence_duration_ms': 500
            }
        )
        text = ' '.join([s.text.strip() for s in segments])
        logger.info(f'STT результат: {text[:100]}')
        return text.strip()
    except Exception as e:
        logger.error(f'STT помилка: {e}')
        return ''


async def transcribe_audio_async(file_path: str) -> str:
    """
    Асинхронна обгортка — запускає STT в окремому потоці
    щоб не блокувати Telegram бота.
    """
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, _transcribe_sync, file_path)
    return text
