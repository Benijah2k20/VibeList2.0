# backend/acousticbrainz_client.py
"""
AcousticBrainz and MusicBrainz integration for audio features.

This allows us to get audio features (energy, valence, tempo, etc.)
without needing Spotify's Extended Quota Mode.

Flow:
1. Search Spotify for tracks
2. Map Spotify track → MusicBrainz Recording ID (MBID)
3. Fetch audio features from AcousticBrainz
4. Return features in Spotify-compatible format
"""
import requests
import time
from typing import Optional, Dict, List
from urllib.parse import quote


# API endpoints
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
ACOUSTICBRAINZ_API = "https://acousticbrainz.org/api/v1"

# Rate limiting (MusicBrainz requires 1 request/second)
LAST_REQUEST_TIME = 0
MIN_REQUEST_INTERVAL = 1.0  # seconds


def _rate_limit():
    """Ensure we don't exceed MusicBrainz rate limits."""
    global LAST_REQUEST_TIME
    current_time = time.time()
    time_since_last = current_time - LAST_REQUEST_TIME
    
    if time_since_last < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - time_since_last)
    
    LAST_REQUEST_TIME = time.time()


def get_musicbrainz_id(track_name: str, artist_name: str, isrc: Optional[str] = None) -> Optional[str]:
    """
    Find MusicBrainz Recording ID (MBID) for a Spotify track.
    
    Args:
        track_name: Name of the track
        artist_name: Name of the artist
        isrc: International Standard Recording Code (if available from Spotify)
    
    Returns:
        MusicBrainz Recording ID (MBID) or None
    """
    _rate_limit()
    
    try:
        # If we have ISRC, use it (most accurate)
        if isrc:
            url = f"{MUSICBRAINZ_API}/isrc/{isrc}"
            params = {"fmt": "json"}
            response = requests.get(url, params=params, headers={"User-Agent": "VibeList/1.0"}, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                recordings = data.get("recordings", [])
                if recordings:
                    return recordings[0]["id"]
        
        # Fallback: Search by track name and artist
        query = f'recording:"{track_name}" AND artist:"{artist_name}"'
        url = f"{MUSICBRAINZ_API}/recording"
        params = {
            "query": query,
            "fmt": "json",
            "limit": 1
        }
        
        response = requests.get(url, params=params, headers={"User-Agent": "VibeList/1.0"}, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            recordings = data.get("recordings", [])
            if recordings:
                return recordings[0]["id"]
        
        return None
        
    except Exception as e:
        print(f"[MusicBrainz] Failed to get MBID for {track_name} - {artist_name}: {e}")
        return None


def get_audio_features(mbid: str) -> Optional[Dict]:
    """
    Fetch audio features from AcousticBrainz for a given MBID.
    
    Args:
        mbid: MusicBrainz Recording ID
    
    Returns:
        Dict with audio features in Spotify-compatible format, or None
    """
    try:
        # Get low-level features from AcousticBrainz
        url = f"{ACOUSTICBRAINZ_API}/{mbid}/low-level"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 404:
            # No analysis available for this track
            return None
        
        if response.status_code != 200:
            print(f"[AcousticBrainz] HTTP {response.status_code} for MBID {mbid}")
            return None
        
        data = response.json()
        
        # Convert AcousticBrainz features to Spotify-compatible format
        features = _convert_to_spotify_format(data)
        return features
        
    except Exception as e:
        print(f"[AcousticBrainz] Failed to get features for MBID {mbid}: {e}")
        return None


def _safe_get(data: dict, *keys, default=0.5):
    """
    Safely extract nested values from AcousticBrainz data.
    Handles both direct values and nested dicts with 'mean' key.
    """
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key, default)
        else:
            return default
    
    # If final value is a dict with 'mean', extract it
    if isinstance(value, dict) and 'mean' in value:
        return value['mean']
    
    # If it's already a number, return it
    if isinstance(value, (int, float)):
        return float(value)
    
    return default


def _convert_to_spotify_format(ab_data: dict) -> dict:
    """
    Convert AcousticBrainz low-level features to Spotify-compatible format.
    
    AcousticBrainz uses different scales and names, so we need to map them.
    """
    try:
        # Extract relevant sections
        rhythm = ab_data.get("rhythm", {})
        tonal = ab_data.get("tonal", {})
        lowlevel = ab_data.get("lowlevel", {})
        
        # Safely extract values
        tempo = _safe_get(rhythm, "bpm", default=120.0)
        loudness = _safe_get(lowlevel, "average_loudness", default=-20.0)
        beats_loudness = _safe_get(rhythm, "beats_loudness", default=0.5)
        
        # Map to Spotify-style features (0-1 scale)
        features = {
            # Tempo (BPM)
            "tempo": tempo,
            
            # Energy: based on loudness and dynamic complexity
            "energy": _normalize_energy(loudness),
            
            # Danceability: based on rhythm regularity and beat strength
            "danceability": _normalize_danceability(beats_loudness),
            
            # Valence (happiness): use tonal features as proxy
            "valence": _estimate_valence(tonal),
            
            # Acousticness: inverse of electronic/synthetic sound
            "acousticness": _estimate_acousticness(lowlevel),
            
            # Speechiness: not directly available
            "speechiness": 0.1,
            
            # Instrumentalness: not directly available
            "instrumentalness": 0.5,
            
            # Liveness: not available
            "liveness": 0.2,
            
            # Loudness (dB)
            "loudness": loudness,
            
            # Key and mode
            "key": int(_safe_get(tonal, "key_key", default=0)),
            "mode": 1 if str(_safe_get(tonal, "key_scale", default="major")).lower() == "major" else 0,
            
            # Time signature
            "time_signature": 4,
        }
        
        return features
        
    except Exception as e:
        print(f"[AcousticBrainz] Feature conversion failed: {e}")
        return None


def _normalize_energy(loudness: float) -> float:
    """Convert loudness (-60 to 0 dB) to energy (0-1)."""
    # Typical range: -60 (silent) to 0 (loud)
    # Map to 0-1 scale
    normalized = (loudness + 60) / 60
    return max(0.0, min(1.0, normalized))


def _normalize_danceability(beats_loudness: float) -> float:
    """Estimate danceability from beat strength."""
    # AcousticBrainz beats_loudness is typically 0-1
    return max(0.0, min(1.0, beats_loudness))


def _estimate_valence(tonal: dict) -> float:
    """
    Estimate valence (happiness) from tonal features.
    Major keys and higher chroma energy tend to sound happier.
    """
    try:
        # Check if key is major (happier) or minor (sadder)
        key_scale = _safe_get(tonal, "key_scale", default="minor")
        is_major = str(key_scale).lower() == "major"
        
        # Chroma energy can indicate brightness
        chroma_energy = _safe_get(tonal, "chroma_energy", default=0.5)
        
        # Combine factors
        valence = 0.3  # Base neutral
        if is_major:
            valence += 0.3
        valence += float(chroma_energy) * 0.2
        
        return max(0.0, min(1.0, valence))
        
    except:
        return 0.5  # Default neutral


def _estimate_acousticness(lowlevel: dict) -> float:
    """
    Estimate acousticness from spectral features.
    Electronic music has different spectral characteristics than acoustic.
    """
    try:
        # Spectral complexity: acoustic instruments have more complex harmonics
        spectral_complexity = _safe_get(lowlevel, "spectral_complexity", default=0.5)
        
        # Inverse relationship: more complex = more acoustic
        return max(0.0, min(1.0, float(spectral_complexity)))
        
    except:
        return 0.5  # Default neutral


def get_features_batch(spotify_tracks: List[dict]) -> Dict[str, dict]:
    """
    Get audio features for a batch of Spotify tracks.
    
    Args:
        spotify_tracks: List of Spotify track objects with 'name', 'artists', 'id'
    
    Returns:
        Dict mapping Spotify track_id -> features
    """
    features_map = {}
    
    for track in spotify_tracks:
        track_id = track.get("id")
        track_name = track.get("name")
        artists = track.get("artists", [])
        
        if not track_id or not track_name or not artists:
            continue
        
        # Get primary artist name
        artist_name = artists[0].get("name", "") if artists else ""
        
        # Optional: Get ISRC if available
        isrc = track.get("external_ids", {}).get("isrc")
        
        # Step 1: Get MusicBrainz ID
        mbid = get_musicbrainz_id(track_name, artist_name, isrc)
        
        if not mbid:
            print(f"[Mapping] No MBID found for: {track_name} - {artist_name}")
            continue
        
        # Step 2: Get audio features from AcousticBrainz
        features = get_audio_features(mbid)
        
        if features:
            features_map[track_id] = features
            print(f"[Features] ✓ {track_name} - {artist_name}")
        else:
            print(f"[Features] ✗ No features for: {track_name} - {artist_name}")
    
    print(f"[AcousticBrainz] Got features for {len(features_map)}/{len(spotify_tracks)} tracks")
    return features_map