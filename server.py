import os
import subprocess
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pyngrok import ngrok

app = FastAPI()

os.makedirs("/content/KazTTS-Studio/static", exist_ok=True)
os.makedirs("/content/KazTTS-Studio/audio_out", exist_ok=True)
os.makedirs("/content/KazTTS-Studio/KazEmoTTS/filelists", exist_ok=True)
os.makedirs("/content/KazTTS-Studio/KazEmoTTS/results", exist_ok=True)

app.mount("/static", StaticFiles(directory="/content/KazTTS-Studio/static"), name="static")

@app.get("/")
def home():
    return FileResponse("/content/KazTTS-Studio/static/index.html")

@app.get("/api/synthesize")
def synth(text: str = "Сәлем UniDauys"):
    out_dir = "/content/KazTTS-Studio/KazEmoTTS/results"
    
    with open("/content/KazTTS-Studio/KazEmoTTS/filelists/text.txt", "w", encoding="utf-8") as f:
        f.write(f"sample|{text}|2|neutral\n")
        
    cmd = 'cd /content/KazTTS-Studio/KazEmoTTS && python3 inference_EMA.py --filelist text.txt --speaker 2 --emotion neutral'
    subprocess.run(cmd, shell=True)
    
    out_file = "/content/KazTTS-Studio/audio_out/master.wav"
    subprocess.run(f'find "{out_dir}" -name "*.wav" -exec cp {{}} "{out_file}" \\; 2>/dev/null', shell=True)
    return {"audio_url": "/audio/master.wav", "status": "ok"}

@app.get("/audio/master.wav")
def get_audio():
    return FileResponse("/content/KazTTS-Studio/audio_out/master.wav", media_type="audio/wav")

if __name__ == "__main__":
    import uvicorn
    ngrok.kill()
    tunnel = ngrok.connect(8000)
    print("\n" + "="*60)
    print("🚀 UniDauys Studio СӘТТІ ҚОСЫЛДЫ!")
    print(f"🔗 СІЛТЕМЕ: {tunnel.public_url}")
    print("="*60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
