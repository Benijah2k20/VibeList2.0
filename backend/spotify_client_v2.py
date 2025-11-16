# backend/spotify_client_v2.py
"""
Fixed Spotify client with:
- Proper scopes for all operations
- Persistent token storage via SQLite
- Automatic token refresh
- Simple, reliable API calls
"""
import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheHandler
from spotipy.exceptions import SpotifyException

from .database import save_token, get_token, delete_token

# Load environment variables
ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(dotenv_path=ENV_PATH)


class DatabaseCacheHandler(CacheHandler):
    """
    Custom Spotipy cache handler that uses our SQLite database.
    This allows Spotipy to automatically refresh tokens using our DB.
    """
    
    def __init__(self, username: str):
        self.username = username
    
    def get_cached_token(self):
        """Get token from database."""
        return get_token(self.username)
    
    def save_token_to_cache(self, token_info):
        """Save token to database."""
        save_token(self.username, token_info)

# CRITICAL: Complete scope list to avoid 403 errors
SCOPES = " ".join([
    "playlist-modify-public",
    "playlist-modify-private",
    "playlist-read-private",
    "user-read-email",
    "user-library-read",
    "user-top-read",
    "user-read-recently-played",
])

DEFAULT_MARKET = "US"


def _get_env(primary: str, alt: str | None = None) -> str:
    """Read env var with optional fallback."""
    val = os.getenv(primary) or (os.getenv(alt) if alt else None)
    if not val:
        hint = f"{primary}" + (f" or {alt}" if alt else "")
        raise RuntimeError(
            f"Missing env var: {hint}. Create backend/.env with:\n"
            "SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI"
        )
    return val


def get_oauth_handler(state: str) -> SpotifyOAuth:
    """Create SpotifyOAuth handler with correct settings."""
    # For OAuth flow, state is the username
    cache_handler = DatabaseCacheHandler(state) if state != "refresh" else None
    
    return SpotifyOAuth(
        client_id=_get_env("SPOTIFY_CLIENT_ID", "SPOTIPY_CLIENT_ID"),
        client_secret=_get_env("SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_SECRET"),
        redirect_uri=_get_env("SPOTIFY_REDIRECT_URI", "SPOTIPY_REDIRECT_URI"),
        scope=SCOPES,
        cache_handler=cache_handler,
        show_dialog=True,
        state=state,
    )


def exchange_code_for_token(state: str, code: str, username: str):
    """Exchange OAuth code for token and save to database."""
    sp_oauth = get_oauth_handler(state)
    token_info = sp_oauth.get_access_token(code, as_dict=True)
    
    if not token_info or "access_token" not in token_info:
        raise RuntimeError("Spotify OAuth failed: no access_token in response")
    
    # Save to database for persistence
    save_token(username, token_info)
    print(f"[Auth] Token saved for user: {username}")


def get_spotify(username: str) -> Spotify:
    """
    Get authenticated Spotify client for a user.
    Automatically refreshes expired tokens.
    """
    token_info = get_token(username)
    
    if not token_info:
        raise RuntimeError(f"No Spotify token for user '{username}'. Please connect first.")
    
    # Create OAuth handler for token refresh
    sp_oauth = get_oauth_handler(username)
    
    # Check if token is expired and refresh if needed
    if sp_oauth.is_token_expired(token_info):
        print(f"[Auth] Token expired for {username}, refreshing...")
        try:
            # Refresh the token
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            # Save updated token to database
            save_token(username, token_info)
            print(f"[Auth] Token refreshed successfully for {username}")
        except Exception as e:
            print(f"[Auth] Failed to refresh token for {username}: {e}")
            raise RuntimeError(f"Token refresh failed. Please reconnect your Spotify account.")
    
    # Create Spotify client with fresh access token
    # Note: We use auth= instead of auth_manager= for simpler, more reliable auth
    return Spotify(auth=token_info["access_token"])


def disconnect_spotify(username: str):
    """Remove user's stored token (logout)."""
    delete_token(username)
    print(f"[Auth] Disconnected Spotify for user: {username}")


# ============ SPOTIFY API HELPERS ============

def get_available_genres(sp: Spotify) -> List[str]:
    """
    Fetch Spotify's available recommendation seed genres.
    Returns fallback list if API fails.
    """
    try:
        # Try both method names (different spotipy versions)
        if hasattr(sp, "recommendation_genre_seeds"):
            result = sp.recommendation_genre_seeds()
        else:
            result = sp.recommendations_available_genre_seeds()
        
        # Handle both dict and list responses
        if isinstance(result, dict):
            genres = result.get("genres", [])
        else:
            genres = list(result or [])
        
        if genres:
            return sorted(genres)
    except Exception as e:
        print(f"[Genres] Failed to fetch from API: {e}")
    
    # Fallback genre list (confirmed working seeds)
    return sorted([
        "acoustic", "afrobeat", "alt-rock", "alternative", "ambient",
        "blues", "chill", "classical", "country", "dance",
        "dancehall", "death-metal", "disco", "drum-and-bass", "dubstep",
        "edm", "electro", "electronic", "emo", "folk",
        "funk", "garage", "gospel", "grime", "grunge",
        "guitar", "hardcore", "heavy-metal", "hip-hop", "house",
        "idm", "indie", "indie-pop", "industrial", "jazz",
        "k-pop", "latin", "metal", "metalcore", "new-age",
        "opera", "party", "piano", "pop", "pop-film",
        "post-dubstep", "power-pop", "progressive-house", "psych-rock", "punk",
        "punk-rock", "r-n-b", "rainy-day", "reggae", "reggaeton",
        "rock", "rock-n-roll", "rockabilly", "romance", "sad",
        "salsa", "samba", "sertanejo", "show-tunes", "singer-songwriter",
        "ska", "sleep", "songwriter", "soul", "soundtracks",
        "spanish", "study", "summer", "synth-pop", "tango",
        "techno", "trance", "trap", "trip-hop", "work-out",
    ])


def search_artists(sp: Spotify, query: str, limit: int = 10) -> List[dict]:
    """Search for artists by name."""
    try:
        result = sp.search(q=query, type="artist", limit=limit, market=DEFAULT_MARKET)
        artists = []
        
        for artist in result.get("artists", {}).get("items", []):
            images = artist.get("images", [])
            artists.append({
                "id": artist["id"],
                "name": artist["name"],
                "image": images[0]["url"] if images else None,
                "genres": artist.get("genres", []),
                "popularity": artist.get("popularity", 0),
                "url": artist["external_urls"]["spotify"],
            })
        
        return artists
    except Exception as e:
        print(f"[Search] Artist search failed: {e}")
        return []


def get_artist_top_tracks(sp: Spotify, artist_id: str, limit: int = 10) -> List[str]:
    """Get top track URIs for an artist."""
    try:
        result = sp.artist_top_tracks(artist_id, country=DEFAULT_MARKET)
        return [track["uri"] for track in result.get("tracks", [])[:limit]]
    except Exception as e:
        print(f"[Artist] Failed to get top tracks for {artist_id}: {e}")
        return []


def get_track_info(sp: Spotify, track_uris: List[str]) -> List[dict]:
    """
    Fetch detailed info for a list of track URIs.
    Returns list of track objects with name, artists, album, etc.
    """
    if not track_uris:
        return []
    
    try:
        track_ids = [uri.split(":")[-1] for uri in track_uris]
        result = sp.tracks(track_ids)
        
        tracks = []
        for track in result.get("tracks", []):
            if not track:
                continue
            
            tracks.append({
                "id": track["id"],
                "uri": track["uri"],
                "name": track["name"],
                "artists": [{"id": a["id"], "name": a["name"]} for a in track.get("artists", [])],
                "album": {
                    "id": track["album"]["id"],
                    "name": track["album"]["name"],
                    "image": track["album"]["images"][0]["url"] if track["album"].get("images") else None,
                },
                "duration_ms": track.get("duration_ms", 0),
                "preview_url": track.get("preview_url"),
                "external_url": track["external_urls"]["spotify"],
            })
        
        return tracks
    except Exception as e:
        print(f"[Tracks] Failed to fetch track info: {e}")
        return []


def get_audio_features(sp: Spotify, track_uris: List[str]) -> dict:
    """
    Fetch audio features for tracks.
    Returns dict mapping track_id -> features.
    """
    if not track_uris:
        return {}
    
    try:
        track_ids = [uri.split(":")[-1] for uri in track_uris]
        result = sp.audio_features(track_ids)
        
        features_map = {}
        for i, features in enumerate(result):
            if features:
                features_map[track_ids[i]] = features
        
        return features_map
    except Exception as e:
        print(f"[Features] Failed to fetch audio features: {e}")
        return {}


def create_playlist(sp: Spotify, user_id: str, name: str, 
                   public: bool = False, description: str = "") -> str:
    """Create a new playlist and return its ID."""
    try:
        playlist = sp.user_playlist_create(
            user=user_id,
            name=name,
            public=public,
            description=description
        )
        return playlist["id"]
    except Exception as e:
        print(f"[Playlist] Failed to create playlist: {e}")
        raise


def add_tracks_to_playlist(sp: Spotify, playlist_id: str, track_uris: List[str]):
    """Add tracks to a playlist."""
    if not track_uris:
        return
    
    try:
        # Spotify API allows max 100 tracks per request
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i:i+100]
            sp.playlist_add_items(playlist_id, batch)
        print(f"[Playlist] Added {len(track_uris)} tracks to playlist {playlist_id}")
    except Exception as e:
        print(f"[Playlist] Failed to add tracks: {e}")
        raise


def get_user_profile(sp: Spotify) -> dict:
    """Get current user's profile information."""
    try:
        user = sp.me()
        return {
            "id": user["id"],
            "display_name": user.get("display_name", user["id"]),
            "email": user.get("email"),
            "country": user.get("country"),
            "product": user.get("product"),
            "images": user.get("images", []),
        }
    except Exception as e:
        print(f"[User] Failed to get profile: {e}")
        raise