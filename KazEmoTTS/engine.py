import os, sys, glob, re, time, base64, subprocess
from pydub import AudioSegment

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def match_target_amplitude(sound: AudioSegment, target_dBFS: float = -20.0) -> AudioSegment:
    change_in_dBFS = target_dBFS - sound.dBFS
    return sound.apply_gain(change_in_dBFS)

def split_to_sentences(text: str):
    raw_parts = re.split(r'([.?!]+)', text)
    sentences = []
    for i in range(0, len(raw_parts)-1, 2):
        s = raw_parts[i].strip() + raw_parts[i+1]
        if s.strip():
            sentences.append(s.strip())
    if len(raw_parts) % 2 == 1 and raw_parts[-1].strip():
        sentences.append(raw_parts[-1].strip())
    return sentences if sentences else [text.strip()]

def synthesize_text(text: str, speaker: int = 2, emotion: int = 0, steps: int = 35, output_file: str = "/tmp/out.wav"):
    sentences = split_to_sentences(text)
    parts_audio = []
    session_id = str(int(time.time() * 1000))
    session_dir = os.path.join(BASE_DIR, f"results/session_{session_id}")
    filelists_dir = os.path.join(BASE_DIR, "filelists")
    os.makedirs(session_dir, exist_ok=True)
    os.makedirs(filelists_dir, exist_ok=True)

    for idx, s in enumerate(sentences):
        in_txt = os.path.join(filelists_dir, f"req_{session_id}_{idx}.txt")
        with open(in_txt, "w", encoding="utf-8") as f:
            f.write(f"{s}|{emotion}|{speaker}\n")
        
        part_out = os.path.join(session_dir, f"seg_{idx}")
        os.makedirs(part_out, exist_ok=True)
        
        cmd = [
            "python3", os.path.join(BASE_DIR, "inference_EMA.py"),
            "-c", os.path.join(BASE_DIR, "configs/train_grad.json"),
            "-m", os.path.join(BASE_DIR, "logs/train_logs"),
            "-t", str(steps),
            "-g", "100",
            "-f", in_txt,
            "-r", part_out
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        wavs = glob.glob(f"{part_out}/*.wav")
        if wavs:
            latest = max(wavs, key=os.path.getctime)
            seg_a = AudioSegment.from_wav(latest)
            seg_a = match_target_amplitude(seg_a, -20.0)
            parts_audio.append(seg_a)
        
        if os.path.exists(in_txt):
            os.remove(in_txt)

    if not parts_audio:
        return None

    master = parts_audio[0]
    for seg in parts_audio[1:]:
        master = master.append(AudioSegment.silent(duration=260), crossfade=10)
        master = master.append(seg, crossfade=25)
    
    master = master.fade_in(30).fade_out(80)
    master.export(output_file, format="wav")
    return output_file
