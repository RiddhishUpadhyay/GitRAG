from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import uuid
import sqlite3

from app.config import settings
from app.database import init_db, get_db_connection
from app.api.auth import LoginRequest, ACTIVE_SESSIONS, hash_password, verify_password, security

# Initialize SQLite database
init_db()

from app.api.routes_ingest import router as ingest_router
from app.api.routes_query import router as query_router

app = FastAPI(
    title="GitRAG Chatbot API",
    description="High-performance RAG-based chatbot for querying GitHub repositories",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(query_router)

@app.post("/api/register")
def register(request: LoginRequest):
    """Registers a new user account in SQLite and automatically logs them in."""
    username = request.username.strip().lower()
    password = request.password
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if username exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username is already taken.")
        
        hashed = hash_password(password)
        cursor.execute(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
            (username, hashed)
        )
        conn.commit()
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()
        
    # Log them in automatically
    token = str(uuid.uuid4())
    ACTIVE_SESSIONS[token] = username
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/login")
def login(request: LoginRequest):
    """Authenticates user credentials and returns a session token."""
    username = request.username.strip().lower()
    password = request.password
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT hashed_password FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not verify_password(row["hashed_password"], password):
        raise HTTPException(status_code=400, detail="Incorrect username or password.")
        
    token = str(uuid.uuid4())
    ACTIVE_SESSIONS[token] = username
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/logout")
def logout(credentials = Depends(security)):
    """Logs out the user and invalidates the session token."""
    token = credentials.credentials
    ACTIVE_SESSIONS.pop(token, None)
    return {"status": "success", "message": "Logged out successfully."}

@app.get("/health")
def health_check():
    return {"status": "ok", "env": settings.ENV}

# We will mount static files when we have them
static_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

@app.get("/")
def read_root():
    return {"message": "Welcome to GitRAG Chatbot API. Serve frontend from /static/index.html"}
