# backend/database.py
"""
SQLite database for persistent token storage and training data collection.
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

DB_PATH = Path(__file__).parent / "vibelist.db"


def init_db():
    """Initialize database tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for Spotify tokens (persistent across server restarts)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spotify_tokens (
            username TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            token_type TEXT,
            scope TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Table for training data (thumbs up/down feedback)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            prompt TEXT NOT NULL,
            vibe_json TEXT NOT NULL,
            track_id TEXT NOT NULL,
            track_name TEXT,
            track_artist TEXT,
            thumbs_up INTEGER NOT NULL,
            energy_slider REAL,
            selected_genres TEXT,
            selected_artists TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Table for generated playlists (history)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            prompt TEXT NOT NULL,
            vibe_json TEXT NOT NULL,
            playlist_id TEXT,
            playlist_url TEXT,
            track_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Index for faster queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_username ON feedback(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_track ON feedback(track_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlists_username ON playlists(username)")
    
    conn.commit()
    conn.close()


# ============ TOKEN MANAGEMENT ============

def save_token(username: str, token_info: dict):
    """Save or update Spotify token for a user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO spotify_tokens 
        (username, access_token, refresh_token, expires_at, token_type, scope, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (
        username,
        token_info.get("access_token"),
        token_info.get("refresh_token"),
        token_info.get("expires_at"),
        token_info.get("token_type"),
        token_info.get("scope"),
    ))
    
    conn.commit()
    conn.close()


def get_token(username: str) -> Optional[dict]:
    """Retrieve stored token for a user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT access_token, refresh_token, expires_at, token_type, scope
        FROM spotify_tokens WHERE username = ?
    """, (username,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "expires_at": row[2],
        "token_type": row[3],
        "scope": row[4],
    }


def delete_token(username: str):
    """Remove a user's token (logout)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM spotify_tokens WHERE username = ?", (username,))
    conn.commit()
    conn.close()


# ============ FEEDBACK/TRAINING DATA ============

def save_feedback(
    username: str,
    prompt: str,
    vibe_json: dict,
    track_id: str,
    track_name: str,
    track_artist: str,
    thumbs_up: bool,
    energy_slider: Optional[float] = None,
    selected_genres: Optional[List[str]] = None,
    selected_artists: Optional[List[str]] = None,
):
    """Save user feedback on a track for training purposes."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO feedback 
        (username, prompt, vibe_json, track_id, track_name, track_artist, 
         thumbs_up, energy_slider, selected_genres, selected_artists)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        username,
        prompt,
        json.dumps(vibe_json),
        track_id,
        track_name,
        track_artist,
        1 if thumbs_up else 0,
        energy_slider,
        json.dumps(selected_genres) if selected_genres else None,
        json.dumps(selected_artists) if selected_artists else None,
    ))
    
    conn.commit()
    conn.close()


def get_feedback_for_training(username: Optional[str] = None) -> List[dict]:
    """
    Retrieve all feedback data for model training.
    Returns list of dicts with all relevant features.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if username:
        cursor.execute("SELECT * FROM feedback WHERE username = ? ORDER BY timestamp DESC", (username,))
    else:
        cursor.execute("SELECT * FROM feedback ORDER BY timestamp DESC")
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


# ============ PLAYLIST HISTORY ============

def save_playlist_history(
    username: str,
    prompt: str,
    vibe_json: dict,
    playlist_id: Optional[str] = None,
    playlist_url: Optional[str] = None,
    track_count: int = 0,
):
    """Save a generated playlist to history."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO playlists 
        (username, prompt, vibe_json, playlist_id, playlist_url, track_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        username,
        prompt,
        json.dumps(vibe_json),
        playlist_id,
        playlist_url,
        track_count,
    ))
    
    conn.commit()
    conn.close()


def get_playlist_history(username: str, limit: int = 20) -> List[dict]:
    """Get user's playlist generation history."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM playlists 
        WHERE username = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (username, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


# Initialize database on import
init_db()
