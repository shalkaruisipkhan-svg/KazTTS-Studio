import os
import sys
import glob
import time
import base64
import subprocess
import runpod

BASE_DIR = "/app/KazEmoTTS"
if os.path.exists(BASE_DIR):
    sys.path.insert(0, BASE_DIR)

def run_tts_synthesis(text, speaker=2, emotion=0, steps=40, output_file="/tmp/output.wav"):
    # 1. Попытка вызвать synthesize_text из engine.py
    try:
        from engine import synthesize_text
        res = synthesize_text(text, speaker=speaker, emotion=emotion, steps=steps, output_file=output_file)
        if res and os.path.exists(output_file):
            return output_file
    except Exception as e:
        print(f"engine.py error: {e}")

    # 2. Прямой гарантированный запуск через inference_EMA.py
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

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    wavs = glob.glob(f"{temp_res_dir}/*.wav")
    if wavs:
        latest = max(wavs, key=os.path.getctime)
        if os.path.exists(output_file):
            os.remove(output_file)
        os.rename(latest, output_file)
        return output_file

    return None

def handler(event):
    job_input = event.get("input", {})
    text = job_input.get("text", "").strip()
    speaker = int(job_input.get("speaker", 2))
    emotion = int(job_input.get("emotion", 0))
    steps = int(job_input.get("steps", 35))

    if not text:
        return {"error": "Text is empty"}

    out_wav = "/tmp/out_result.wav"
    res = run_tts_synthesis(text, speaker=speaker, emotion=emotion, steps=steps, output_file=out_wav)

    if not res or not os.path.exists(out_wav):
        return {"error": "Failed to synthesize speech audio"}

    with open(out_wav, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return {"audio_base64": b64}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
