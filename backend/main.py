# backend/main.py
"""
Updated FastAPI backend for VibeList with fixed authentication and recommendations.
"""
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from typing import Optional

from .ai_engine import analyze_vibe_to_json
from .spotify_client_v2 import (
    get_oauth_handler,
    exchange_code_for_token,
    get_spotify,
    disconnect_spotify,
    get_available_genres,
    search_artists,
    get_track_info,
    create_playlist,
    add_tracks_to_playlist,
    get_user_profile,
)
from .recommend_engine import recommend_tracks
from .database import save_feedback, save_playlist_history, get_playlist_history

# Frontend URL
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "http://localhost:3000")

app = FastAPI(title="VibeList API", version="2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== HEALTH CHECKS ====================

@app.get("/")
def root():
    return {"message": "VibeList API v2 - Ready!", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ollama")
def health_ollama():
    """Check if Ollama is running and accessible."""
    import requests
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        r.raise_for_status()
        return {"ok": True, "ollama": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama not reachable: {e}")


# ==================== SPOTIFY AUTH ====================

@app.get("/spotify/login")
def spotify_login(username: str):
    """
    Generate Spotify OAuth URL for user to authorize.
    Frontend should redirect user to this URL.
    """
    if not username:
        raise HTTPException(400, "username parameter required")
    
    try:
        oauth_handler = get_oauth_handler(state=username)
        auth_url = oauth_handler.get_authorize_url()
        return {"auth_url": auth_url}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate auth URL: {str(e)}")


@app.get("/spotify/callback")
def spotify_callback(code: str, state: str):
    """
    OAuth callback - Spotify redirects here after user authorizes.
    Exchanges code for token and redirects back to frontend.
    """
    try:
        username = state  # We use username as state
        exchange_code_for_token(state, code, username)
        return RedirectResponse(url=f"{FRONTEND_BASE}?spotify_connected=true&username={username}")
    except Exception as e:
        error_msg = str(e).replace(" ", "_")
        return RedirectResponse(url=f"{FRONTEND_BASE}?spotify_error={error_msg}")


@app.post("/spotify/disconnect")
def spotify_disconnect(username: str):
    """Disconnect user's Spotify account."""
    try:
        disconnect_spotify(username)
        return {"success": True, "message": "Spotify disconnected"}
    except Exception as e:
        raise HTTPException(500, f"Failed to disconnect: {str(e)}")


@app.get("/spotify/status")
def spotify_status(username: str):
    """Check if user's Spotify is connected."""
    try:
        sp = get_spotify(username)
        user = get_user_profile(sp)
        return {
            "connected": True,
            "user": user,
        }
    except:
        return {"connected": False}


# ==================== SPOTIFY DATA ====================

@app.get("/spotify/genres")
def get_genres(username: str):
    """Get available Spotify genre seeds."""
    try:
        sp = get_spotify(username)
        genres = get_available_genres(sp)
        return {"genres": genres}
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch genres: {str(e)}")


@app.get("/spotify/search/artists")
def search_artists_endpoint(username: str, query: str, limit: int = 10):
    """Search for artists."""
    if not query.strip():
        raise HTTPException(400, "Query parameter required")
    
    try:
        sp = get_spotify(username)
        artists = search_artists(sp, query, limit=min(limit, 20))
        return {"artists": artists}
    except Exception as e:
        raise HTTPException(500, f"Artist search failed: {str(e)}")


# ==================== VIBE ANALYSIS ====================

@app.post("/vibe/analyze")
def analyze_vibe(prompt: str):
    """
    Analyze a vibe prompt using AI to get structured parameters.
    Returns JSON with energy, valence, genres, tempo, etc.
    """
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required")
    
    try:
        params = analyze_vibe_to_json(prompt)
        return params
    except Exception as e:
        raise HTTPException(500, f"Vibe analysis failed: {str(e)}")


# ==================== PLAYLIST GENERATION ====================

@app.post("/playlist/generate")
def generate_playlist(
    username: str,
    prompt: str,
    limit: int = Query(15, ge=5, le=50),
    energy: Optional[float] = None,
    genres: Optional[str] = None,
    artists: Optional[str] = None,
    only_selected_artists: bool = False,
):
    """
    Generate playlist recommendations (does NOT create Spotify playlist yet).
    
    Returns track URIs and info for user to review/thumbs up or down.
    
    Parameters:
    - username: User's identifier
    - prompt: Vibe description (e.g., "rooftop pregame")
    - limit: Number of tracks (default 15)
    - energy: Optional energy override (0-1)
    - genres: Comma-separated genre names
    - artists: Comma-separated artist IDs
    - only_selected_artists: If true, use ONLY tracks from selected artists
    """
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required")
    
    try:
        # Step 1: Analyze vibe with AI
        vibe_params = analyze_vibe_to_json(prompt)
        print(f"\n[Generate] Vibe analysis: {vibe_params}")
        
        # Step 2: Parse user inputs
        user_artist_ids = [a.strip() for a in (artists or "").split(",") if a.strip()]
        user_genres = [g.strip() for g in (genres or "").split(",") if g.strip()]
        
        # Step 3: Get Spotify client
        sp = get_spotify(username)
        
        # Step 4: Generate recommendations
        track_uris = recommend_tracks(
            sp=sp,
            vibe_params=vibe_params,
            n=limit,
            user_artist_ids=user_artist_ids if user_artist_ids else None,
            user_genres=user_genres if user_genres else None,
            energy_override=energy,
        )
        
        if not track_uris:
            raise HTTPException(400, "No tracks found matching your criteria. Try adjusting your vibe or selections.")
        
        # Step 5: Fetch track details for frontend
        tracks = get_track_info(sp, track_uris[:limit])
        
        return {
            "tracks": tracks,
            "vibe_params": vibe_params,
            "count": len(tracks),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Playlist generation failed: {str(e)}")


@app.post("/playlist/create")
def create_spotify_playlist(
    username: str,
    prompt: str,
    track_uris: str,  # Comma-separated URIs
    public: bool = False,
):
    """
    Create actual Spotify playlist with approved tracks.
    Call this AFTER user has reviewed tracks from /playlist/generate.
    
    Parameters:
    - username: User's identifier
    - prompt: Original vibe prompt (for playlist name)
    - track_uris: Comma-separated track URIs to add
    - public: Whether playlist should be public
    """
    if not track_uris.strip():
        raise HTTPException(400, "track_uris required")
    
    try:
        # Parse URIs
        uris = [u.strip() for u in track_uris.split(",") if u.strip()]
        if not uris:
            raise HTTPException(400, "No valid track URIs provided")
        
        # Get Spotify client
        sp = get_spotify(username)
        user_profile = get_user_profile(sp)
        
        # Analyze vibe for playlist name
        vibe_params = analyze_vibe_to_json(prompt)
        mood = vibe_params.get("mood", "mix")
        
        # Create playlist
        playlist_name = f"VibeList • {mood}"
        playlist_desc = f"Generated by VibeList for: {prompt}"
        
        playlist_id = create_playlist(
            sp=sp,
            user_id=user_profile["id"],
            name=playlist_name,
            public=public,
            description=playlist_desc,
        )
        
        # Add tracks
        add_tracks_to_playlist(sp, playlist_id, uris)
        
        # Get playlist URL
        playlist_info = sp.playlist(playlist_id, fields="external_urls.spotify")
        playlist_url = playlist_info["external_urls"]["spotify"]
        
        # Save to history
        save_playlist_history(
            username=username,
            prompt=prompt,
            vibe_json=vibe_params,
            playlist_id=playlist_id,
            playlist_url=playlist_url,
            track_count=len(uris),
        )
        
        return {
            "success": True,
            "playlist_id": playlist_id,
            "playlist_url": playlist_url,
            "track_count": len(uris),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to create playlist: {str(e)}")


# ==================== FEEDBACK (TRAINING DATA) ====================

@app.post("/feedback/submit")
def submit_feedback(
    username: str,
    prompt: str,
    track_id: str,
    track_name: str,
    track_artist: str,
    thumbs_up: bool,
    vibe_json: str = "{}",  # JSON string
    energy: Optional[float] = None,
    genres: Optional[str] = None,
    artists: Optional[str] = None,
):
    """
    Submit thumbs up/down feedback on a track.
    This data is saved for future model training.
    """
    try:
        import json
        vibe_dict = json.loads(vibe_json) if vibe_json else {}
        
        genre_list = [g.strip() for g in (genres or "").split(",") if g.strip()]
        artist_list = [a.strip() for a in (artists or "").split(",") if a.strip()]
        
        save_feedback(
            username=username,
            prompt=prompt,
            vibe_json=vibe_dict,
            track_id=track_id,
            track_name=track_name,
            track_artist=track_artist,
            thumbs_up=thumbs_up,
            energy_slider=energy,
            selected_genres=genre_list if genre_list else None,
            selected_artists=artist_list if artist_list else None,
        )
        
        return {"success": True, "message": "Feedback saved"}
    
    except Exception as e:
        raise HTTPException(500, f"Failed to save feedback: {str(e)}")


@app.get("/feedback/history")
def get_feedback_history(username: str, limit: int = 50):
    """Get user's feedback history."""
    from .database import get_feedback_for_training
    
    try:
        feedback = get_feedback_for_training(username)
        return {"feedback": feedback[:limit]}
    except Exception as e:
        raise HTTPException(500, f"Failed to retrieve feedback: {str(e)}")


# ==================== PLAYLIST HISTORY ====================

@app.get("/playlists/history")
def playlist_history(username: str, limit: int = 20):
    """Get user's playlist generation history."""
    try:
        history = get_playlist_history(username, limit=limit)
        return {"playlists": history}
    except Exception as e:
        raise HTTPException(500, f"Failed to retrieve history: {str(e)}")


# ==================== REPLACE TRACK ====================

@app.post("/playlist/replace")
def replace_track(
    username: str,
    prompt: str,
    exclude_uris: str,  # Comma-separated URIs to exclude
    energy: Optional[float] = None,
    genres: Optional[str] = None,
    artists: Optional[str] = None,
):
    """
    Generate a replacement track when user thumbs down a song.
    Returns 1 new track that fits the vibe but wasn't in the original list.
    """
    try:
        # Parse exclusions
        excluded = set(u.strip() for u in (exclude_uris or "").split(",") if u.strip())
        
        # Analyze vibe
        vibe_params = analyze_vibe_to_json(prompt)
        
        # Parse user inputs
        user_artist_ids = [a.strip() for a in (artists or "").split(",") if a.strip()]
        user_genres = [g.strip() for g in (genres or "").split(",") if g.strip()]
        
        # Get more recommendations
        sp = get_spotify(username)
        track_uris = recommend_tracks(
            sp=sp,
            vibe_params=vibe_params,
            n=50,  # Get more to find non-excluded tracks
            user_artist_ids=user_artist_ids if user_artist_ids else None,
            user_genres=user_genres if user_genres else None,
            energy_override=energy,
        )
        
        # Find first track that's not excluded
        for uri in track_uris:
            if uri not in excluded:
                tracks = get_track_info(sp, [uri])
                if tracks:
                    return {"track": tracks[0]}
        
        raise HTTPException(404, "No replacement track found")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to find replacement: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)