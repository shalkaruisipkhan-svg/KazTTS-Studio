import os
import sys
import glob
import time
import base64
import subprocess
import collections
import collections.abc
from pydub import AudioSegment

collections.Mapping = collections.abc.Mapping
collections.MutableMapping = collections.abc.MutableMapping
collections.Sequence = collections.abc.Sequence
collections.MutableSequence = collections.abc.MutableSequence

import runpod

BASE_DIR = "/app/KazEmoTTS"
if os.path.exists(BASE_DIR):
    sys.path.insert(0, BASE_DIR)

EMOTION_MAP = {
    "angry": 0, "fear": 1, "happy": 2,
    "neutral": 3, "sad": 4, "surprise": 5
}

def synthesize_one_chunk(text, speaker=2, emotion=3, steps=35, output_file="/tmp/output.wav"):
    errors = []
    os.makedirs(f"{BASE_DIR}/filelists", exist_ok=True)
    temp_res_dir = f"/tmp/runpod_tts_{int(time.time()*1000)}"
    os.makedirs(temp_res_dir, exist_ok=True)

    input_file = f"{BASE_DIR}/filelists/inference_generated.txt"
    with open(input_file, "w", encoding="utf-8") as f:
        f.write(f"{text}|{emotion}|{speaker}\n")

    cmd = [
        "python3", f"{BASE_DIR}/inference_EMA.py",
        "-c", f"{BASE_DIR}/configs/train_grad.json",
        "-m", f"{BASE_DIR}/logs/train_logs",
        "-t", str(steps),
        "-g", "100",
        "-f", input_file,
        "-r", temp_res_dir
    ]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=BASE_DIR)
    if p.returncode != 0:
        errors.append(f"Returncode {p.returncode}: Stderr={p.stderr[:400]}")

    wavs = glob.glob(f"{temp_res_dir}/*.wav")
    if wavs:
        latest = max(wavs, key=os.path.getctime)
        if os.path.exists(output_file):
            os.remove(output_file)
        os.rename(latest, output_file)
        return output_file, None

    return None, " ; ".join(errors)

def handler(event):
    job_input = event.get("input", {})
    text = job_input.get("text", "").strip()
    speaker = int(job_input.get("speaker", 2))
    steps = int(job_input.get("steps", 35))
    is_ai_mode = bool(job_input.get("is_ai_mode", False))
    segments = job_input.get("segments")

    # 1. ЖИ көпкейіпкерлі режимі (әр рөлді өз дикторымен оқытып, біріктіру)
    if is_ai_mode and segments and isinstance(segments, list):
        audio_chunks = []
        pause = AudioSegment.silent(duration=250)
        for idx, seg in enumerate(segments):
            seg_text = seg.get("text", "").strip()
            if not seg_text:
                continue
            seg_spk = int(seg.get("speaker_id", 2))
            emo_str = str(seg.get("emotion", "neutral")).lower()
            emo_id = EMOTION_MAP.get(emo_str, 3)
            
            chunk_file = f"/tmp/seg_{idx}_{int(time.time()*1000)}.wav"
            res, err = synthesize_one_chunk(seg_text, speaker=seg_spk, emotion=emo_id, steps=steps, output_file=chunk_file)
            if res and os.path.exists(chunk_file):
                try:
                    audio_chunks.append(AudioSegment.from_wav(chunk_file))
                except Exception:
                    pass
                try:
                    os.remove(chunk_file)
                except Exception:
                    pass
        
        if audio_chunks:
            final_audio = audio_chunks[0]
            for ch in audio_chunks[1:]:
                final_audio = final_audio + pause + ch
            
            merged_wav = "/tmp/out_result.wav"
            final_audio.export(merged_wav, format="wav")
            with open(merged_wav, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return {"audio_base64": b64}

    # 2. Қарапайым бір дауысты синтез
    if not text:
        return {"error": "Text is empty"}

    out_wav = "/tmp/out_result.wav"
    res, err = synthesize_one_chunk(text, speaker=speaker, emotion=3, steps=steps, output_file=out_wav)
    if not res or not os.path.exists(out_wav):
        return {"error": f"Synthesis failed: {err}"}

    with open(out_wav, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return {"audio_base64": b64}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
