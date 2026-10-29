import os
import sys
import glob
import uuid
import shutil
import base64
import tempfile
import subprocess
import collections
import collections.abc
from pydub import AudioSegment

collections.Mapping = collections.abc.Mapping
collections.MutableMapping = collections.abc.MutableMapping
collections.Sequence = collections.abc.Sequence
collections.MutableSequence = collections.abc.MutableSequence

import runpod

BASE_DIR = os.getenv("KAZ_REPO", "/app/KazEmoTTS")
INFER_PY = os.getenv("INFER_PY", "python3")
INFER_TIMEOUT = int(os.getenv("INFER_TIMEOUT", "600"))
if os.path.exists(BASE_DIR):
    sys.path.insert(0, BASE_DIR)

EMOTION_MAP = {"angry": 0, "fear": 1, "happy": 2, "neutral": 3, "sad": 4, "surprise": 5}
MAX_SEGMENTS = 80
MAX_CHARS = 3000


class SynthError(Exception):
    pass


def clean_text(text):
    text = str(text).replace("|", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(text.split()).strip()


def synthesize_one_chunk(text, speaker=2, emotion=3, steps=35):
    job = tempfile.mkdtemp(prefix="tts_")
    out_dir = os.path.join(job, "out")
    os.makedirs(out_dir)
    try:
        flist = os.path.join(job, "line.txt")
        with open(flist, "w", encoding="utf-8") as f:
            f.write(f"{text}|{emotion}|{speaker}\n")
        cmd = [INFER_PY, os.path.join(BASE_DIR, "inference_EMA.py"),
               "-c", os.path.join(BASE_DIR, "configs/train_grad.json"),
               "-m", os.path.join(BASE_DIR, "logs/train_logs"),
               "-t", str(int(steps)), "-g", "100", "-f", flist, "-r", out_dir]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                           cwd=BASE_DIR, timeout=INFER_TIMEOUT)
        wavs = glob.glob(os.path.join(out_dir, "*.wav"))
        if p.returncode != 0 or not wavs:
            tail = (p.stderr or "")[-1500:]
            raise SynthError(f"inference rc={p.returncode} text={text[:60]!r} stderr_tail=...{tail}")
        return AudioSegment.from_wav(max(wavs, key=os.path.getctime))
    finally:
        shutil.rmtree(job, ignore_errors=True)


def match_amplitude(sound, target=-20.0):
    if sound.dBFS == float("-inf"):
        return sound
    return sound.apply_gain(target - sound.dBFS)


def apply_speed(sound, speed):
    if abs(speed - 1.0) < 0.05:
        return sound
    src = dst = None
    try:
        fd, src = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        fd, dst = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        sound.export(src, format="wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-filter:a", f"atempo={speed:.3f}", dst],
                       check=True, timeout=60)
        return AudioSegment.from_wav(dst)
    except Exception as e:
        print(f"[speed] ffmpeg жоқ немесе қате ({type(e).__name__}), резервтік әдіс")
        altered = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * speed)})
        return altered.set_frame_rate(sound.frame_rate)
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


def pause_between(prev_role, role, prev_text, frame_rate):
    if prev_role != role:
        ms = 400
    elif prev_text.endswith(("!", "?")):
        ms = 350
    elif prev_text.endswith("..."):
        ms = 500
    else:
        ms = 240
    return AudioSegment.silent(duration=ms, frame_rate=frame_rate)


def safe_append(a, b, crossfade):
    cf = int(min(crossfade, len(a) // 2, len(b) // 2))
    return a.append(b, crossfade=cf) if cf > 0 else a + b


def to_b64(sound):
    path = os.path.join(tempfile.gettempdir(), f"out_{uuid.uuid4().hex}.wav")
    try:
        sound.export(path, format="wav")
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def handler(event):
    job_input = event.get("input", {}) or {}
    try:
        text = clean_text(job_input.get("text", ""))
        speaker = max(0, min(2, int(job_input.get("speaker", 2))))
        steps = max(10, min(100, int(job_input.get("steps", 35))))
        speed = max(0.5, min(2.0, float(job_input.get("speed", 1.0))))
        is_ai_mode = bool(job_input.get("is_ai_mode", False))
        segments = job_input.get("segments")

        if is_ai_mode and isinstance(segments, list) and segments:
            if len(segments) > MAX_SEGMENTS:
                return {"error": "Too many segments"}
            parts = []
            for seg in segments:
                seg_text = clean_text(seg.get("text", ""))
                if not seg_text:
                    continue
                parts.append((str(seg.get("role", "narrator")), seg_text,
                              max(0, min(2, int(seg.get("speaker_id", 2)))),
                              EMOTION_MAP.get(str(seg.get("emotion", "neutral")).lower(), 3)))
            if not parts:
                return {"error": "Valid segments list is empty"}
            if sum(len(p[1]) for p in parts) > MAX_CHARS:
                return {"error": "Text too long"}

            master = None
            for i, (role, seg_text, spk, emo) in enumerate(parts):
                audio = apply_speed(match_amplitude(synthesize_one_chunk(seg_text, spk, emo, steps)), speed)
                if master is None:
                    master = audio
                else:
                    pr = parts[i - 1]
                    master = safe_append(master, pause_between(pr[0], role, pr[1], master.frame_rate), 10)
                    master = safe_append(master, audio, 30)
            master = master.fade_in(50).fade_out(150)
            return {"audio_base64": to_b64(master), "mode": "ai_director"}

        if not text:
            return {"error": "Text is empty"}
        if len(text) > MAX_CHARS:
            return {"error": "Text too long"}
        audio = synthesize_one_chunk(text, speaker, 3, steps)
        audio = apply_speed(match_amplitude(audio), speed).fade_in(30).fade_out(100)
        return {"audio_base64": to_b64(audio), "mode": "single"}
    except SynthError as e:
        print(f"[handler] {e}", flush=True)
        return {"error": f"Synthesis failed: {str(e)[-700:]}"}
    except Exception as e:
        print(f"[handler] {type(e).__name__}: {e}", flush=True)
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
