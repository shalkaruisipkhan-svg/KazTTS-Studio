FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# 1. Системные пакеты и звуковые библиотеки
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    python3-dev \
    libsndfile1 \
    ffmpeg \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# 2. Инструменты сборки со строгой фиксацией numpy<2
RUN pip install --no-cache-dir --upgrade pip setuptools wheel cython "numpy<2.0.0"

# 3. Копируем проект
COPY . /app

# 4. Полный комплект библиотек для KazEmoTTS
RUN pip install --no-cache-dir \
    "numpy<2.0.0" \
    matplotlib \
    torchaudio \
    torchvision \
    unidecode \
    phonemizer \
    einops \
    pydub \
    kaldiio \
    soundfile \
    scipy \
    librosa \
    num2words \
    attrdict \
    runpod \
    fastapi \
    uvicorn \
    requests

# 5. Сборка monotonic_align
WORKDIR /app/KazEmoTTS/model/monotonic_align
RUN python3 setup.py build_ext --inplace

WORKDIR /app

# 6. Запуск
CMD ["python3", "-u", "handler.py"]
