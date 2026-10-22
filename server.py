# -*- coding: utf-8 -*-
import os
import re
import glob
import time
import uuid
import shutil
import sqlite3
import threading
import subprocess
import jwt
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from pydub import AudioSegment
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = FastAPI(title="UniDauys Studio Official Google Auth Backend")

BASE_DIR = "/content/KazTTS-Studio"
STATIC_DIR = os.path.join(BASE_DIR, "static")
AUDIO_OUT_DIR = os.path.join(BASE_DIR, "audio_out")
EMO_DIR = os.path.join(BASE_DIR, "KazEmoTTS")
DB_PATH = os.path.join(BASE_DIR, "kaztts.db")

GOOGLE_CLIENT_ID = "190507005188-09p3t7lq1kr8i0pmknso865rvc9n8g1m.apps.googleusercontent.com"
JWT_SECRET = "unidauys-super-secret-key-2026"

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AUDIO_OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(EMO_DIR, "filelists"), exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

generation_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                full_name TEXT,
                picture TEXT,
                balance INTEGER DEFAULT 5000,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                text_preview TEXT,
                char_count INTEGER,
                audio_url TEXT,
                speaker INTEGER,
                speed REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.commit()

init_db()

def create_jwt_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "exp": time.time() + 30 * 86400}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_jwt_token(token: str) -> Optional[Dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None

def get_current_user_id(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    payload = decode_jwt_token(token)
    return payload.get("sub") if payload else None

EMOTION_MAP = {"angry": 0, "fear": 1, "happy": 2, "neutral": 3, "sad": 4, "surprise": 5}

class GoogleLoginRequest(BaseModel):
    credential: str

class SynthesizeRequest(BaseModel):
    text: str = Field(..., max_length=3000)
    speaker: int = Field(2, ge=0, le=2)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    steps: int = Field(100, ge=10, le=100)

@app.get("/")
def landing():
    return FileResponse(os.path.join(STATIC_DIR, "landing.html"))


# --- ҚҰҚЫҚТЫҚ ҚҰЖАТТАРДЫҢ ЖЕКЕ МАРШРУТТАРЫ ---
@app.get("/terms", response_class=FileResponse)
def get_terms_page():
    return FileResponse("static/legal/terms.html")

@app.get("/refunds", response_class=FileResponse)
def get_refunds_page():
    return FileResponse("static/legal/refunds.html")

@app.get("/privacy", response_class=FileResponse)
def get_privacy_page():
    return FileResponse("static/legal/privacy.html")

@app.get("/consent", response_class=FileResponse)
def get_consent_page():
    return FileResponse("static/legal/consent.html")

@app.get("/studio")
def studio():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))



# --- ТОЛЫҚ БІРІКТІРІЛГЕН АВТОРИЗАЦИЯ (ЛОГИН + EMAIL + GOOGLE) ---
class UserRegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str

class UserLoginRequest(BaseModel):
    username: str
    password: str

def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

@app.post("/api/auth/register")
def register_user(req: UserRegisterRequest):
    uname = req.full_name.strip()
    email = req.email.strip().lower()
    
    if len(uname) < 3:
        raise HTTPException(status_code=400, detail="Логин кемінде 3 таңбадан тұруы керек")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Жарамды электронды пошта енгізіңіз")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Құпия сөз кемінде 6 таңбадан тұруы керек")

    user_id = f"usr_{uuid.uuid4().hex[:10]}"
    pwd_hash = hash_pw(req.password)

    with get_db() as conn:
        existing_email = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing_email:
            raise HTTPException(status_code=400, detail="Бұл email бойынша аккаунт тіркелген. Кіру бөлімін пайдаланыңыз.")
        
        existing_user = conn.execute("SELECT id FROM users WHERE LOWER(username) = ? OR LOWER(full_name) = ?", (uname.lower(), uname.lower())).fetchone()
        if existing_user:
            raise HTTPException(status_code=400, detail="Бұл логин бос емес! Басқа логин таңдаңыз.")
        
        conn.execute("""
            INSERT INTO users (id, email, full_name, username, hashed_password, balance)
            VALUES (?, ?, ?, ?, ?, 5000)
        """, (user_id, email, uname, uname.lower(), pwd_hash))
        conn.commit()

    token = create_jwt_token(user_id, email)
    return {
        "status": "success",
        "token": token,
        "user": {"id": user_id, "name": uname, "email": email, "balance": 5000}
    }

@app.post("/api/auth/login")
def login_user(req: UserLoginRequest):
    login_id = req.username.strip().lower()
    pwd_hash = hash_pw(req.password)

    with get_db() as conn:
        user = conn.execute("""
            SELECT id, email, full_name, username, hashed_password, balance 
            FROM users 
            WHERE LOWER(username) = ? OR LOWER(full_name) = ? OR LOWER(email) = ?
        """, (login_id, login_id, login_id)).fetchone()
        
        if not user or user["hashed_password"] != pwd_hash:
            raise HTTPException(status_code=401, detail="Логин/пошта немесе құпия сөз қате!")

    token = create_jwt_token(user["id"], user["email"])
    return {
        "status": "success",
        "token": token,
        "user": {"id": user["id"], "name": user["full_name"], "balance": user["balance"]}
    }

@app.post("/api/auth/google")
def google_auth(req: GoogleLoginRequest):
    try:
        id_info = id_token.verify_oauth2_token(
            req.credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
        email = id_info.get("email")
        google_sub = id_info.get("sub")
        name = id_info.get("name", "Creator")
        picture = id_info.get("picture", "")

        user_id = f"usr_{google_sub[:12]}"

        with get_db() as conn:
            user = conn.execute("SELECT id, balance, full_name, picture FROM users WHERE email = ?", (email,)).fetchone()
            if not user:
                conn.execute("""
                    INSERT INTO users (id, email, full_name, picture, balance)
                    VALUES (?, ?, ?, ?, 5000)
                """, (user_id, email, name, picture))
                conn.commit()
                balance = 5000
            else:
                user_id = user["id"]
                balance = user["balance"]
                conn.execute("UPDATE users SET full_name = ?, picture = ? WHERE id = ?", (name, picture, user_id))
                conn.commit()

        token = create_jwt_token(user_id, email)
        return {
            "token": token,
            "user": {
                "id": user_id,
                "name": name,
                "email": email,
                "picture": picture,
                "balance": balance
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Google Auth қатесі: {str(e)}")

@app.get("/api/user/info")
def get_user_info(authorization: Optional[str] = Header(None)):
    user_id = get_current_user_id(authorization)
    if not user_id:
        # Егер әлі кірмесе, қонақ ретінде уақытша демо көрсетеді
        return {
            "is_authenticated": False,
            "user": {"name": "Қонақ (Guest)", "picture": "", "balance": 0},
            "projects": []
        }

    with get_db() as conn:
        user = conn.execute("SELECT id, full_name, email, picture, balance FROM users WHERE id = ?", (user_id,)).fetchone()
        projects = conn.execute(
            "SELECT id, title, text_preview, char_count, audio_url, speaker, created_at FROM projects WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user_id,)
        ).fetchall()

    return {
        "is_authenticated": True,
        "user": dict(user) if user else {"name": "Creator", "balance": 0, "picture": ""},
        "projects": [dict(p) for p in projects]
    }

TAG_RE = re.compile(r'\((happyert{}sadert{}angryert{}surpriseert{}fearert{}neutralert{}pauseert{}кідіріс)\)', re.I)
SENT_RE = re.compile(r'(?<=[.!?…])\s+')

def split_text_to_chunks(raw_text: str, default_emo: str = "neutral", max_len: int = 200) -> List[Dict]:
    segments = []
    current_emo = default_emo
    parts = TAG_RE.split(raw_text)

    for i, part in enumerate(parts):
        if i % 2 == 1:
            token = part.lower()
            if token in ["pause", "кідіріс"]:
                segments.append({"type": "pause", "duration": 800})
            else:
                current_emo = token
            continue

        clean_part = re.sub(r'[\r\n|]+', ' ', part).strip()
        if not clean_part:
            continue

        for s in SENT_RE.split(clean_part):
            s = s.strip()
            while len(s) > max_len:
                cut = s.rfind(',', 0, max_len)
                if cut < 40:
                    cut = s.rfind(' ', 0, max_len)
                if cut < 40:
                    cut = max_len
                piece, s = s[:cut + 1].strip(), s[cut + 1:].strip()
                if re.search(r'\w', piece):
                    segments.append({"type": "speech", "text": piece, "emotion": current_emo})
            if re.search(r'\w', s):
                segments.append({"type": "speech", "text": s, "emotion": current_emo})

    return segments

def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', os.path.basename(s))]

@app.post("/api/synthesize")
def synthesize(req: SynthesizeRequest, authorization: Optional[str] = Header(None)):
    user_id = get_current_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Дыбыстау үшін алдымен Google арқылы кіріңіз!")

    raw_text = req.text.strip()
    char_count = len(raw_text)
    if char_count == 0:
        raise HTTPException(status_code=400, detail="Мәтін бос")

    # Балансты тексеру
    with get_db() as conn:
        user = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or user["balance"] < char_count:
            raise HTTPException(status_code=402, detail=f"Таңба балансы жеткіліксіз! Қажет: {char_count}, Қалғаны: {user['balance'] if user else 0}.")

    chunks = split_text_to_chunks(raw_text)
    speech_chunks = [c for c in chunks if c["type"] == "speech"]
    if not speech_chunks:
        raise HTTPException(status_code=400, detail="Дыбыстауға сөз табылмады")

    if not generation_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Сервер бос емес. Күте тұрыңыз.")

    req_id = str(uuid.uuid4())[:8]
    session_dir = os.path.join(EMO_DIR, "results", f"session_{req_id}")
    os.makedirs(session_dir, exist_ok=True)
    filelist_abs = os.path.join(EMO_DIR, f"filelists/batch_{req_id}.txt")
    calc_timeout = 60 + 25 * len(speech_chunks)

    try:
        with open(filelist_abs, "w", encoding="utf-8") as f:
            for c in speech_chunks:
                emo_id = EMOTION_MAP.get(c["emotion"], 3)
                f.write(f"{c['text']}|{emo_id}|{req.speaker}\n")

        cmd = [
            "python3", "inference_EMA.py",
            "-c", "configs/train_grad.json",
            "-m", "train_logs",
            "-t", str(req.steps),
            "-g", "100",
            "-f", f"filelists/batch_{req_id}.txt",
            "-r", session_dir
        ]

        res = subprocess.run(cmd, cwd=EMO_DIR, capture_output=True, text=True, timeout=calc_timeout)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail="Модель қатесі")

        wav_files = sorted(glob.glob(f"{session_dir}/**/*.wav", recursive=True), key=natural_sort_key)
        if not wav_files:
            wav_files = sorted(glob.glob(f"{session_dir}/*.wav"), key=natural_sort_key)

        default_pause = AudioSegment.silent(duration=250)
        combined_audio = AudioSegment.empty()
        speech_idx = 0

        for chunk in chunks:
            if chunk["type"] == "pause":
                combined_audio += AudioSegment.silent(duration=chunk["duration"])
            elif chunk["type"] == "speech":
                speech_seg = AudioSegment.from_wav(wav_files[speech_idx])
                if len(combined_audio) > 0:
                    combined_audio += default_pause
                combined_audio += speech_seg
                speech_idx += 1

        temp_master = os.path.join(session_dir, "master_raw.wav")
        combined_audio.export(temp_master, format="wav")

        unique_filename = f"UniDauys_{req_id}.wav"
        final_audio_path = os.path.join(AUDIO_OUT_DIR, unique_filename)

        actual_speed = req.speed
        if abs(req.speed - 1.0) > 0.05:
            ff_cmd = ["ffmpeg", "-y", "-i", temp_master, "-filter:a", f"atempo={req.speed}", "-vn", final_audio_path]
            ff_res = subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ff_res.returncode != 0 or not os.path.exists(final_audio_path):
                shutil.copy(temp_master, final_audio_path)
                actual_speed = 1.0
        else:
            shutil.copy(temp_master, final_audio_path)

        audio_url = f"/api/audio/{unique_filename}"

        # Баланстан шегеру және жобаны базаға тіркеу
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (char_count, user_id))
            conn.execute("""
                INSERT INTO projects (id, user_id, title, text_preview, char_count, audio_url, speaker, speed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (req_id, user_id, raw_text[:30] + "...", raw_text[:80], char_count, audio_url, req.speaker, actual_speed))
            conn.commit()
            updated_user = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()

        return {
            "status": "success",
            "id": req_id,
            "audio_url": audio_url,
            "new_balance": updated_user["balance"],
            "segments_count": len(speech_chunks),
            "text": raw_text[:60]
        }

    finally:
        generation_lock.release()
        if os.path.exists(filelist_abs):
            try: os.remove(filelist_abs)
            except: pass
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)

@app.get("/api/audio/{filename}")
def serve_audio(filename: str):
    clean_name = os.path.basename(filename)
    file_path = os.path.join(AUDIO_OUT_DIR, clean_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Аудио файл табылмады")
    return FileResponse(file_path, media_type="audio/wav")
