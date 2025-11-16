# backend/recommend_engine.py
"""
Clean, effective recommendation engine.

Strategy:
1. Make ONE smart Spotify recommendations call with tight filters
2. Request 100 tracks to have good selection
3. Score each track by vibe match
4. Apply diversity rules
5. Return top N tracks
"""
import random
from typing import List, Dict, Optional
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

try:
    from .acousticbrainz_client import get_features_batch
    ACOUSTICBRAINZ_AVAILABLE = True
except ImportError:
    ACOUSTICBRAINZ_AVAILABLE = False
    print("[Warning] AcousticBrainz client not available")


# Genres that frequently cause problems (overly broad or wrong results)
GENRE_BLACKLIST = {
    "country", "contemporary-country", "classic-country",
    "bluegrass", "honky-tonk", "country-pop",
}


def recommend_tracks(
    sp: Spotify,
    vibe_params: dict,
    n: int = 35,
    user_artist_ids: Optional[List[str]] = None,
    user_genres: Optional[List[str]] = None,
    energy_override: Optional[float] = None,
) -> List[str]:
    """
    Generate playlist recommendations based on vibe parameters.
    
    Args:
        sp: Authenticated Spotify client
        vibe_params: Dict from AI analysis (energy_range, valence_range, etc.)
        n: Number of tracks to return
        user_artist_ids: Optional list of artist IDs to use as seeds/filters
        user_genres: Optional list of genres to use (overrides AI genres)
        energy_override: Optional energy level from user slider (0-1)
    
    Returns:
        List of track URIs
    """
    print(f"\n[Recommend] Starting recommendation for {n} tracks")
    
    # Parse vibe parameters
    energy_range = vibe_params.get("energy_range", [0.5, 0.7])
    valence_range = vibe_params.get("valence_range", [0.5, 0.7])
    danceability_range = vibe_params.get("danceability_range", [0.4, 0.7])
    acousticness_range = vibe_params.get("acousticness_range", [0.2, 0.6])
    tempo_bpm = vibe_params.get("tempo_bpm", 100)
    
    # Apply energy override if provided
    if energy_override is not None:
        energy_val = max(0.0, min(1.0, energy_override))
        energy_range = [energy_val, energy_val]
        print(f"[Recommend] Energy override applied: {energy_val}")
    
    # Calculate target values (midpoint of ranges)
    target_energy = sum(energy_range) / 2
    target_valence = sum(valence_range) / 2
    target_danceability = sum(danceability_range) / 2
    target_acousticness = sum(acousticness_range) / 2
    
    # Determine genres to use
    if user_genres:
        genres = _normalize_genres(sp, user_genres)
        print(f"[Recommend] User genres: {genres}")
    else:
        ai_genres = vibe_params.get("genre_candidates", [])
        genres = _normalize_genres(sp, ai_genres)
        print(f"[Recommend] AI genres: {genres}")
    
    # Build seed parameters (max 5 total seeds)
    seed_artists = []
    seed_genres = []
    seed_tracks = []
    
    # Priority 1: User-selected artists (if any)
    if user_artist_ids:
        seed_artists = user_artist_ids[:2]  # Max 2 artist seeds
        print(f"[Recommend] Using {len(seed_artists)} artist seeds")
    
    # Priority 2: Genres
    remaining_seeds = 5 - len(seed_artists)
    if genres and remaining_seeds > 0:
        seed_genres = genres[:remaining_seeds]
        print(f"[Recommend] Using {len(seed_genres)} genre seeds")
    
    # Ensure we have at least one seed
    if not seed_artists and not seed_genres:
        seed_genres = ["pop"]  # Safe fallback
        print("[Recommend] No seeds provided, using 'pop' as fallback")
    
    # STEP 1: Call Spotify recommendations API
    candidate_uris = _fetch_recommendations(
        sp,
        seed_artists=seed_artists,
        seed_genres=seed_genres,
        target_energy=target_energy,
        target_valence=target_valence,
        target_danceability=target_danceability,
        target_acousticness=target_acousticness,
        target_tempo=tempo_bpm,
        limit=100,
    )
    
    print(f"[Recommend] Received {len(candidate_uris)} candidates from Spotify")
    
    # STEP 2: If we have selected artists, guarantee some of their tracks
    if user_artist_ids:
        artist_tracks = _get_artist_tracks(sp, user_artist_ids, max_per_artist=10)
        candidate_uris.extend(artist_tracks)
        candidate_uris = list(dict.fromkeys(candidate_uris))  # Remove duplicates
        print(f"[Recommend] Added artist tracks, total candidates: {len(candidate_uris)}")
    
    # STEP 2.5: If recommendations API failed, use search as fallback
    if not candidate_uris:
        print("[Recommend] Recommendations API failed, using search fallback...")
        search_tracks = _search_fallback(sp, vibe_params, genres, user_artist_ids, limit=n*3)
        candidate_uris.extend(search_tracks)
        candidate_uris = list(dict.fromkeys(candidate_uris))
        print(f"[Recommend] Search fallback returned {len(candidate_uris)} candidates")
    
    if not candidate_uris:
        print("[Recommend] WARNING: No candidates found!")
        return []
    
    # STEP 3: Fetch audio features for all candidates
    features_map = _fetch_audio_features(sp, candidate_uris)
    
    # STEP 4: Score each track by vibe match
    scored_tracks = []
    for uri in candidate_uris:
        track_id = uri.split(":")[-1]
        features = features_map.get(track_id)
        
        # If no features available (403 error), give neutral score
        if not features:
            scored_tracks.append((uri, 0.5, {}))
        else:
            # Calculate vibe match score (0-1, higher is better)
            score = _calculate_vibe_score(
                features,
                target_energy=target_energy,
                target_valence=target_valence,
                target_danceability=target_danceability,
                target_acousticness=target_acousticness,
                target_tempo=tempo_bpm,
            )
            scored_tracks.append((uri, score, features))
    
    # Sort by score (best first)
    scored_tracks.sort(key=lambda x: x[1], reverse=True)
    print(f"[Recommend] Top 5 scores: {[round(s, 2) for _, s, _ in scored_tracks[:5]]}")
    
    # STEP 5: Apply diversity rules and select top N
    final_uris = _apply_diversity(sp, scored_tracks, n, user_artist_ids)
    
    print(f"[Recommend] Returning {len(final_uris)} tracks")
    return final_uris


def _normalize_genres(sp: Spotify, genres: List[str]) -> List[str]:
    """
    Normalize genre names to match Spotify's available seeds.
    Filters out blacklisted genres.
    """
    if not genres:
        return []
    
    # Get available genres from Spotify
    try:
        if hasattr(sp, "recommendation_genre_seeds"):
            result = sp.recommendation_genre_seeds()
        else:
            result = sp.recommendations_available_genre_seeds()
        
        if isinstance(result, dict):
            available = set(result.get("genres", []))
        else:
            available = set(result or [])
    except:
        # Fallback if API fails
        available = {"pop", "rock", "hip-hop", "electronic", "indie", "alternative"}
    
    # Normalize input genres
    normalized = []
    for genre in genres:
        g = str(genre).lower().strip()
        
        # Skip blacklisted genres
        if g in GENRE_BLACKLIST:
            continue
        
        # Check if it's valid
        if g in available:
            normalized.append(g)
    
    return normalized[:5]  # Max 5 genres


def _fetch_recommendations(
    sp: Spotify,
    seed_artists: List[str],
    seed_genres: List[str],
    target_energy: float,
    target_valence: float,
    target_danceability: float,
    target_acousticness: float,
    target_tempo: int,
    limit: int = 100,
) -> List[str]:
    """
    Make ONE smart call to Spotify recommendations API.
    Returns list of track URIs.
    """
    # Add target parameters with small jitter for variety
    def jitter(val, spread=0.05):
        """Add small random variation."""
        return round(max(0.0, min(1.0, val + random.uniform(-spread, spread))), 2)
    
    # Build base kwargs WITHOUT market initially
    kwargs = {
        "limit": min(limit, 100),  # API max is 100
    }
    
    # Add seeds
    if seed_artists:
        kwargs["seed_artists"] = seed_artists
    if seed_genres:
        kwargs["seed_genres"] = seed_genres
    
    kwargs["target_energy"] = jitter(target_energy)
    kwargs["target_valence"] = jitter(target_valence)
    kwargs["target_danceability"] = jitter(target_danceability)
    kwargs["target_acousticness"] = jitter(target_acousticness)
    kwargs["target_tempo"] = target_tempo + random.randint(-5, 5)
    
    print(f"[API] Calling recommendations with seeds: {len(seed_artists)} artists, {len(seed_genres)} genres")
    
    # Try without market first (works more reliably)
    try:
        result = sp.recommendations(**kwargs)
        tracks = result.get("tracks", [])
        if tracks:
            print(f"[API] Success! Got {len(tracks)} tracks")
            return [track["uri"] for track in tracks if track.get("uri")]
    except Exception as e:
        print(f"[API] First attempt failed: {e}")
    
    # Fallback: Try with just seeds, no targets
    print("[API] Trying fallback without target parameters...")
    try:
        simple_kwargs = {"limit": limit}
        if seed_artists:
            simple_kwargs["seed_artists"] = seed_artists
        if seed_genres:
            simple_kwargs["seed_genres"] = seed_genres
        
        result = sp.recommendations(**simple_kwargs)
        tracks = result.get("tracks", [])
        if tracks:
            print(f"[API] Fallback successful, got {len(tracks)} tracks")
            return [track["uri"] for track in tracks if track.get("uri")]
    except Exception as e:
        print(f"[API] Fallback also failed: {e}")
    
    return []


def _search_fallback(sp: Spotify, vibe_params: dict, genres: List[str], artist_ids: Optional[List[str]], limit: int = 50) -> List[str]:
    """
    Fallback when recommendations API fails.
    Uses search API to find tracks matching the vibe.
    """
    tracks = []
    
    # Build search queries based on vibe
    queries = []
    
    # Use genres for search
    if genres:
        for genre in genres[:3]:  # Top 3 genres
            queries.append(f'genre:{genre}')
    
    # Use mood/keywords
    keywords = vibe_params.get('keywords', [])
    mood = vibe_params.get('mood', '')
    if keywords:
        queries.append(' '.join(keywords[:2]))
    elif mood:
        queries.append(mood)
    
    # Default fallback queries
    if not queries:
        queries = ['popular music', 'top hits']
    
    # Search for tracks
    for query in queries[:5]:  # Max 5 queries
        try:
            result = sp.search(q=query, type='track', limit=20)
            for track in result.get('tracks', {}).get('items', []):
                if track and track.get('uri'):
                    tracks.append(track['uri'])
                    if len(tracks) >= limit:
                        break
            if len(tracks) >= limit:
                break
        except Exception as e:
            print(f"[Search] Query '{query}' failed: {e}")
            continue
    
    return tracks[:limit]


def _get_artist_tracks(sp: Spotify, artist_ids: List[str], max_per_artist: int = 5) -> List[str]:
    """Get top tracks from selected artists."""
    tracks = []
    for artist_id in artist_ids[:5]:  # Max 5 artists
        try:
            result = sp.artist_top_tracks(artist_id, country="US")
            for track in result.get("tracks", [])[:max_per_artist]:
                if track.get("uri"):
                    tracks.append(track["uri"])
        except Exception as e:
            print(f"[Artist] Failed to get tracks for {artist_id}: {e}")
    
    return tracks


def _fetch_audio_features(sp: Spotify, track_uris: List[str]) -> Dict[str, dict]:
    """
    Fetch audio features for tracks using AcousticBrainz.
    Falls back to Spotify if AcousticBrainz is not available.
    Returns dict mapping track_id -> features.
    """
    if not track_uris:
        return {}
    
    track_ids = [uri.split(":")[-1] for uri in track_uris]
    
    # Use AcousticBrainz if available
    if ACOUSTICBRAINZ_AVAILABLE:
        print(f"[Features] Using AcousticBrainz for {len(track_ids)} tracks...")
        
        # Fetch full track info from Spotify (needed for mapping)
        try:
            spotify_tracks = sp.tracks(track_ids[:50]).get("tracks", [])  # Limit to 50 for speed
            features_map = get_features_batch(spotify_tracks)
            
            if features_map:
                print(f"[Features] AcousticBrainz returned {len(features_map)} feature sets")
                return features_map
            else:
                print("[Features] AcousticBrainz returned no features, tracks will get neutral scores")
                return {}
        except Exception as e:
            print(f"[Features] AcousticBrainz failed: {e}")
            return {}
    
    # Fallback to Spotify (will likely fail in Development Mode)
    print(f"[Features] Trying Spotify audio features API...")
    features_map = {}
    for i in range(0, len(track_ids), 100):
        batch = track_ids[i:i+100]
        try:
            result = sp.audio_features(batch)
            for j, features in enumerate(result):
                if features:
                    features_map[batch[j]] = features
        except Exception as e:
            print(f"[Features] Spotify API failed (expected in Dev Mode): {e}")
    
    return features_map


def _calculate_vibe_score(
    features: dict,
    target_energy: float,
    target_valence: float,
    target_danceability: float,
    target_acousticness: float,
    target_tempo: int,
) -> float:
    """
    Calculate how well a track matches the target vibe.
    Returns score from 0-1 (higher is better).
    """
    # Calculate individual feature matches (1.0 = perfect match, 0.0 = far off)
    energy_match = 1.0 - abs(features.get("energy", 0.5) - target_energy)
    valence_match = 1.0 - abs(features.get("valence", 0.5) - target_valence)
    dance_match = 1.0 - abs(features.get("danceability", 0.5) - target_danceability)
    acoustic_match = 1.0 - abs(features.get("acousticness", 0.5) - target_acousticness)
    
    # Tempo match: within ±20 BPM is good, falls off linearly
    tempo = features.get("tempo", target_tempo)
    tempo_diff = abs(tempo - target_tempo)
    tempo_match = max(0.0, 1.0 - (tempo_diff / 50.0))
    
    # Weighted average (prioritize energy and valence for vibe)
    score = (
        energy_match * 0.30 +
        valence_match * 0.25 +
        dance_match * 0.20 +
        acoustic_match * 0.15 +
        tempo_match * 0.10
    )
    
    return score


def _apply_diversity(
    sp: Spotify,
    scored_tracks: List[tuple],
    n: int,
    preferred_artist_ids: Optional[List[str]] = None,
) -> List[str]:
    """
    Select top N tracks while ensuring diversity.
    
    Rules:
    - Max 2-3 tracks per artist (unless user specifically selected that artist)
    - Boost tracks from preferred artists
    - Shuffle within score tiers for variety
    """
    final_uris = []
    artist_count = {}
    
    # Fetch track info to get artist IDs
    all_uris = [uri for uri, _, _ in scored_tracks]
    track_info = {}
    
    try:
        track_ids = [uri.split(":")[-1] for uri in all_uris]
        result = sp.tracks(track_ids[:100])  # Limit to avoid huge request
        for track in result.get("tracks", []):
            if track:
                track_info[track["uri"]] = track
    except:
        pass
    
    # Select tracks with diversity rules
    for uri, score, features in scored_tracks:
        if len(final_uris) >= n:
            break
        
        # Get artist info
        track = track_info.get(uri)
        if not track or not track.get("artists"):
            continue
        
        primary_artist_id = track["artists"][0]["id"]
        current_count = artist_count.get(primary_artist_id, 0)
        
        # Diversity rules
        if preferred_artist_ids and primary_artist_id in preferred_artist_ids:
            # Preferred artists: allow up to 4 tracks
            max_per_artist = 4
        else:
            # Other artists: max 2 tracks
            max_per_artist = 2
        
        if current_count >= max_per_artist:
            continue
        
        final_uris.append(uri)
        artist_count[primary_artist_id] = current_count + 1
    
    # If we're still short, loosen restrictions
    if len(final_uris) < n:
        for uri, score, features in scored_tracks:
            if len(final_uris) >= n:
                break
            if uri not in final_uris:
                final_uris.append(uri)
    
    return final_uris