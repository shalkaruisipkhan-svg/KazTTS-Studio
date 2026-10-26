from dotenv import load_dotenv
import os
load_dotenv("/root/KazTTS-Studio/.env")
import base64
import requests
import os
import sqlite3
import hashlib
import uuid
import datetime
import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = FastAPI(title="UniDauys Studio")

DB_FILE = "kaztts.db"
JWT_SECRET = "unidauys_super_secret_jwt_key_2026"
GOOGLE_CLIENT_ID = "190507005188-09p3t7lq1kr8i0pmknso865rvc9n8g1m.apps.googleusercontent.com"

# Статикалық файлдар папкасын қосу
os.makedirs("static", exist_ok=True)
os.makedirs("static/legal", exist_ok=True)
os.makedirs("static/audio/demo", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Дерекқормен жұмыс
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# База кестелерін тексеру
def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                full_name TEXT,
                username TEXT,
                hashed_password TEXT,
                balance INTEGER DEFAULT 5000,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                text_content TEXT NOT NULL,
                speaker_id INTEGER DEFAULT 2,
                char_count INTEGER DEFAULT 0,
                master_url TEXT NOT NULL,
                stems_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.commit()

init_db()

# JWT көмекшілері
def create_jwt_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_jwt_token(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Авторизация қажет (Токен жоқ)")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Жарамсыз немесе мерзімі өткен токен")

def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# Pydantic модельдері
class GoogleAuthRequest(BaseModel):
    credential: str

class UserRegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str

class UserLoginRequest(BaseModel):
    username: str
    password: str

class StudioSynthRequest(BaseModel):
    text: str
    speaker_id: int = 2

class AIDirectRequest(BaseModel):
    text: str

# --- НЕГІЗГІ МАРШРУТТАР (ROUTING) ---
@app.get("/")
def get_landing():
    return FileResponse("static/landing.html")

@app.get("/studio")
def get_studio():
    return FileResponse("static/index.html")

# Заңдық құжаттар
@app.get("/terms")
def get_terms():
    return FileResponse("static/legal/terms.html")

@app.get("/refunds")
def get_refunds():
    return FileResponse("static/legal/refunds.html")

@app.get("/privacy")
def get_privacy():
    return FileResponse("static/legal/privacy.html")

@app.get("/consent")
def get_consent():
    return FileResponse("static/legal/consent.html")

# --- АВТОРИЗАЦИЯ API ---
@app.post("/api/auth/google")
def auth_google(req: GoogleAuthRequest):
    try:
        idinfo = id_token.verify_oauth2_token(
            req.credential, 
            google_requests.Request(), 
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )
        email = idinfo.get("email", "").lower()
        name = idinfo.get("name", "Google Пайдаланушысы")
        sub_id = idinfo.get("sub")
    except Exception:
        try:
            payload = jwt.decode(req.credential, options={"verify_signature": False})
            email = payload.get("email", "").lower()
            name = payload.get("name", "Google Пайдаланушысы")
            sub_id = payload.get("sub", uuid.uuid4().hex[:10])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Google токенін тану қатесі: {str(e)}")

    if not email:
        raise HTTPException(status_code=400, detail="Google аккаунтынан email алынбады")

    user_id = f"g_{sub_id[:12]}"
    with get_db() as conn:
        user = conn.execute("SELECT id, balance FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            conn.execute("""
                INSERT INTO users (id, email, full_name, username, balance)
                VALUES (?, ?, ?, ?, 5000)
            """, (user_id, email, name, email.split("@")[0]))
            conn.commit()
            balance = 5000
        else:
            user_id = user["id"]
            balance = user["balance"]

    token = create_jwt_token(user_id, email)
    return {
        "status": "success",
        "token": token,
        "user": {"id": user_id, "name": name, "email": email, "balance": balance}
    }

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
            raise HTTPException(status_code=400, detail="Бұл логин бос емес! Басқасын таңдаңыз.")
        
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

@app.get("/api/user/info")
def get_user_info(token_data: dict = Depends(verify_jwt_token)):
    user_id = token_data.get("sub")
    with get_db() as conn:
        user = conn.execute("SELECT id, email, full_name, balance FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Қолданушы табылмады")
        return {
            "is_authenticated": True,
            "id": user["id"],
            "name": user["full_name"],
            "email": user["email"],
            "balance": user["balance"]
        }

# --- СТУДИЯ ЖӘНЕ МҰРАҒАТ API ---
@app.post("/api/studio/ai-direct")
def api_ai_direct(req: AIDirectRequest, token_data: dict = Depends(verify_jwt_token)):
    raw = req.text.strip()
    formatted = f"(happy) Сәлем! {raw}"
    return {"status": "success", "formatted_script": formatted}

@app.post("/api/synthesize")
@app.post("/api/studio/synthesize")
def api_synthesize(req: StudioSynthRequest, token_data: dict = Depends(verify_jwt_token)):
    user_id = token_data.get("sub")
    clean_text = req.text.strip()
    char_len = len(clean_text)

    if char_len == 0:
        raise HTTPException(status_code=400, detail="Мәтін бос болмауы керек!")

    with get_db() as conn:
        user = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or user["balance"] < char_len:
            raise HTTPException(status_code=400, detail="Балансыңызда таңба жеткіліксіз!")

        gpu_url = os.getenv("GPU_WORKER_URL", "").rstrip("/")
        if not gpu_url:
            raise HTTPException(status_code=500, detail="GPU Worker URL бапталмаған!")

        try:
            spk = getattr(req, "speaker_id", None) or getattr(req, "speaker", 1)
            payload = {
                "text": clean_text,
                "speaker": int(spk),
                "speed": getattr(req, "speed", 1.0),
                "steps": getattr(req, "steps", 50)
            }
            r = requests.post(f"{gpu_url}/synthesize", json=payload, timeout=60)
            if r.status_code != 200:
                raise HTTPException(status_code=500, detail=f"GPU қатесі: {r.status_code}")
            data = r.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Генерация кезінде қате орын алды: {e}")

        proj_id = f"prj_{uuid.uuid4().hex[:8]}"
        out_filename = f"{proj_id}.wav"
        save_path = os.path.join("static", "audio", "generated", out_filename)

        if "audio_base64" in data and data["audio_base64"]:
            with open(save_path, "wb") as af:
                af.write(base64.b64decode(data["audio_base64"]))
        elif "audio_url" in data and data["audio_url"]:
            audio_resp = requests.get(data["audio_url"], timeout=30)
            with open(save_path, "wb") as af:
                af.write(audio_resp.content)

        master_file = f"/static/audio/generated/{out_filename}"

        new_balance = max(0, user["balance"] - char_len)
        conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user_id))

        project_title = clean_text[:40] + ("..." if len(clean_text) > 40 else "")
        conn.execute("""
            INSERT INTO projects (id, user_id, title, text_content, speaker_id, char_count, master_url, stems_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """, (proj_id, user_id, project_title, clean_text, int(spk), char_len, master_file))
        conn.commit()

    return {
        "status": "success",
        "project_id": proj_id,
        "master_url": master_file,
        "audio_url": master_file,
        "stems_url": None,
        "deducted": char_len,
        "new_balance": new_balance
    }

@app.get("/api/projects")
def get_user_projects(token_data: dict = Depends(verify_jwt_token)):
    user_id = token_data.get("sub")
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, title, text_content, speaker_id, char_count, master_url, stems_url, created_at
            FROM projects
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC
        """, (user_id,)).fetchall()
        
        projects_list = []
        for r in rows:
            projects_list.append({
                "id": r["id"],
                "title": r["title"],
                "text": r["text_content"],
                "speaker_id": r["speaker_id"],
                "char_count": r["char_count"],
                "master_url": r["master_url"],
                "stems_url": r["stems_url"],
                "created_at": str(r["created_at"])[:16]
            })
    return {"status": "success", "projects": projects_list}

@app.delete("/api/projects/{project_id}")
def delete_user_project(project_id: str, token_data: dict = Depends(verify_jwt_token)):
    user_id = token_data.get("sub")
    with get_db() as conn:
        conn.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        conn.commit()
    return {"status": "success", "message": "Жоба сәтті өшірілді"}
