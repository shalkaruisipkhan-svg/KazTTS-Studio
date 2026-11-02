import os
import sys
import glob
import time
import base64
import zipfile
import secrets
import subprocess
import collections
import collections.abc
from pydub import AudioSegment

# attrdict пен Python 3.10 үйлесімділік патчы
collections.Mapping = collections.abc.Mapping
collections.MutableMapping = collections.abc.MutableMapping
collections.Sequence = collections.abc.Sequence
collections.MutableSequence = collections.abc.MutableSequence

import runpod

BASE_DIR = "/app/KazEmoTTS"
if os.path.exists(BASE_DIR):
    sys.path.insert(0, BASE_DIR)

EMOTION_MAP = {
    "neutral": 0,
    "happy": 1,
    "sad": 2,
    "angry": 3,
    "fear": 4,
    "surprise": 5
}

def run_tts_synthesis(text, speaker=2, emotion=0, steps=35, output_file="/tmp/output.wav"):
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
        errors.append(f"Returncode {p.returncode}: Stderr={p.stderr[:400]} | Stdout={p.stdout[:400]}")

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
    segments = job_input.get("segments", [])

    # 8 таңбалы бірегей UID (4 байт = 8 hex таңба)
    uid = secrets.token_hex(4)
    work_dir = f"/tmp/tts_{uid}"
    os.makedirs(work_dir, exist_ok=True)

    # 1. РӨЛДІК РЕЖИМ (AI-режиссер)
    if is_ai_mode and isinstance(segments, list) and len(segments) > 0:
        combined_audio = AudioSegment.empty()
        silence_pause = AudioSegment.silent(duration=350)  # Репликалар арасындағы 350мс кідіріс
        stem_files = []

        for idx, seg in enumerate(segments):
            seg_text = str(seg.get("text", "")).strip()
            if not seg_text:
                continue
            seg_spk = int(seg.get("speaker_id", speaker))
            seg_emo_str = str(seg.get("emotion", "neutral")).lower()
            seg_emo = EMOTION_MAP.get(seg_emo_str, 0)
            role_name = str(seg.get("role", "narrator")).lower()

            take_filename = f"{idx+1:02d}_{role_name}_{seg_emo_str}_{uid}.wav"
            take_path = os.path.join(work_dir, take_filename)

            res, err = run_tts_synthesis(seg_text, speaker=seg_spk, emotion=seg_emo, steps=steps, output_file=take_path)
            if not res or not os.path.exists(take_path):
                return {"error": f"Segment {idx+1} synthesis failed: {err}"}

            stem_files.append((take_filename, take_path))
            part_audio = AudioSegment.from_wav(take_path)
            if len(combined_audio) > 0:
                combined_audio += silence_pause
            combined_audio += part_audio

        if not stem_files:
            return {"error": "No valid segments were synthesized"}

        # Master тректі сақтау
        master_path = os.path.join(work_dir, f"master_{uid}.wav")
        combined_audio.export(master_path, format="wav")

        # dialogues_stems_{uid}.zip архивін жасау
        zip_path = os.path.join(work_dir, f"dialogues_stems_{uid}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for fname, fpath in stem_files:
                zipf.write(fpath, arcname=fname)

        with open(master_path, "rb") as mf:
            master_b64 = base64.b64encode(mf.read()).decode("utf-8")
        with open(zip_path, "rb") as zf:
            zip_b64 = base64.b64encode(zf.read()).decode("utf-8")

        return {
            "uid": uid,
            "audio_base64": master_b64,
            "stems_zip_base64": zip_b64
        }

    # 2. ЖЕКЕ (СТАНДАРТТЫ) РЕЖИМ
    if not text:
        return {"error": "Text is empty"}

    emotion = int(job_input.get("emotion", 0))
    master_path = os.path.join(work_dir, f"master_{uid}.wav")
    res, err = run_tts_synthesis(text, speaker=speaker, emotion=emotion, steps=steps, output_file=master_path)

    if not res or not os.path.exists(master_path):
        return {"error": f"Synthesis failed: {err}"}

    with open(master_path, "rb") as mf:
        master_b64 = base64.b64encode(mf.read()).decode("utf-8")

    return {
        "uid": uid,
        "audio_base64": master_b64,
        "stems_zip_base64": None
    }

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})