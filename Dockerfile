FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# 1. Системные пакеты и звуковые библиотеки
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    wget \
    unzip \
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

# 5. Сборка модуля monotonic_align
WORKDIR /app/KazEmoTTS/model/monotonic_align
RUN python3 setup.py build_ext --inplace

# 6. Гарантированная загрузка весов Grad-TTS и HiFi-GAN
WORKDIR /app/KazEmoTTS
RUN mkdir -p logs/train_logs checkpts results filelists && \
    wget -q -O /tmp/tts_ckpt.zip https://issai.nu.edu.kz/wp-content/uploads/2024/03/pt_10000.zip && \
    unzip -q -o /tmp/tts_ckpt.zip -d logs/train_logs/ && \
    (cp logs/train_logs/pt_10000/EMA_grad_10000.pt logs/train_logs/EMA_grad_10000.pt || true) && \
    wget -q -O /tmp/hifigan_ckpt.zip https://issai.nu.edu.kz/wp-content/uploads/2024/03/pre_trained_hf.zip && \
    unzip -q -o /tmp/hifigan_ckpt.zip -d checkpts/ && \
    (cp "checkpts/pre_trained 3/g_01720000" checkpts/hifigan.pt || cp checkpts/*/g_* checkpts/hifigan.pt || true) && \
    rm -f /tmp/*.zip

WORKDIR /app

# 7. Запуск сервиса
CMD ["python3", "-u", "handler.py"]
