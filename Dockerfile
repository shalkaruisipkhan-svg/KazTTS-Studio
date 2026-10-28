FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# 1. Установка системных компиляторов и звуковых библиотек
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    python3-dev \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 2. Установка базовых инструментов сборки для Cython
RUN pip install --no-cache-dir --upgrade pip setuptools wheel cython numpy

# 3. Копируем проект
COPY . /app

# 4. Установка Python-зависимостей
RUN pip install --no-cache-dir runpod fastapi uvicorn requests soundfile scipy

# 5. Компиляция модуля monotonic_align (исправляет ошибку exit code 2)
WORKDIR /app/KazEmoTTS/model/monotonic_align
RUN python3 setup.py build_ext --inplace

WORKDIR /app

# 6. Запуск воркера RunPod
CMD ["python3", "-u", "handler.py"]
