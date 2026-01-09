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
    only_selected_artists: bool = False,
) -> List[str]:
    """
    Generate playlist recommendations based on vibe parameters.
    
    NEW STRATEGY: Search-first approach with artist control
    
    Args:
        sp: Authenticated Spotify client
        vibe_params: Dict from AI analysis (energy_range, valence_range, etc.)
        n: Number of tracks to return
        user_artist_ids: Optional list of artist IDs to use as seeds/filters
        user_genres: Optional list of genres to use (overrides AI genres)
        energy_override: Optional energy level from user slider (0-1)
        only_selected_artists: If True, ONLY return tracks from selected artists
    
    Returns:
        List of track URIs
    """
    print(f"\n[Recommend] Starting recommendation for {n} tracks")
    
    if only_selected_artists:
        print(f"[Recommend] ONLY SELECTED ARTISTS MODE - Will only return tracks from chosen artists")
    elif user_artist_ids:
        print(f"[Recommend] INCLUDE ARTISTS MODE - Will prioritize {len(user_artist_ids)} selected artists")
    
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
    
    # === ONLY SELECTED ARTISTS MODE ===
    if only_selected_artists and user_artist_ids:
        print(f"[Recommend] Searching ONLY within {len(user_artist_ids)} selected artist(s)")
        
        # Get extensive catalog from selected artists
        artist_tracks = _get_artist_extensive_catalog(sp, user_artist_ids, max_per_artist=50)
        
        if not artist_tracks:
            print("[Recommend] WARNING: No tracks found from selected artists!")
            return []
        
        print(f"[Recommend] Found {len(artist_tracks)} tracks from selected artists")
        
        # Score these tracks by vibe match
        features_map = _fetch_audio_features(sp, artist_tracks)
        scored_tracks = []
        
        for uri in artist_tracks:
            track_id = uri.split(":")[-1]
            features = features_map.get(track_id)
            
            if not features:
                scored_tracks.append((uri, 0.5, {}))
            else:
                score = _calculate_vibe_score(
                    features,
                    target_energy=target_energy,
                    target_valence=target_valence,
                    target_danceability=target_danceability,
                    target_acousticness=target_acousticness,
                    target_tempo=tempo_bpm,
                )
                scored_tracks.append((uri, score, features))
        
        # Sort by score
        scored_tracks.sort(key=lambda x: x[1], reverse=True)
        print(f"[Recommend] Top 5 scores: {[round(s, 2) for _, s, _ in scored_tracks[:5]]}")
        
        # Return top N
        final_uris = [uri for uri, _, _ in scored_tracks[:n]]
        print(f"[Recommend] Returning {len(final_uris)} tracks (only from selected artists)")
        return final_uris
    
    # === NORMAL MODE (Include selected artists) ===
    
    # STEP 1: Try Spotify recommendations API (may fail in Dev Mode, that's OK)
    print("[Recommend] Attempting Spotify Recommendations API...")
    rec_tracks = _fetch_recommendations(
        sp,
        seed_artists=user_artist_ids[:2] if user_artist_ids else [],
        seed_genres=genres[:3] if genres else [],
        target_energy=target_energy,
        target_valence=target_valence,
        target_danceability=target_danceability,
        target_acousticness=target_acousticness,
        target_tempo=tempo_bpm,
        limit=100,
    )
    print(f"[Recommend] Recommendations API returned {len(rec_tracks)} tracks")
    
    # STEP 2: INTELLIGENT SEARCH - This is our main source now
    print("[Recommend] Running intelligent vibe-based search...")
    search_tracks = _intelligent_search(
        sp,
        vibe_params=vibe_params,
        genres=genres,
        user_artist_ids=user_artist_ids,
        limit=100
    )
    print(f"[Recommend] Intelligent search returned {len(search_tracks)} tracks")
    
    # STEP 3: Get EXTENSIVE tracks from selected artists (if specified)
    artist_tracks = []
    if user_artist_ids:
        # Get MORE tracks from selected artists to ensure they appear
        artist_tracks = _get_artist_extensive_catalog(sp, user_artist_ids, max_per_artist=30)
        print(f"[Recommend] Added {len(artist_tracks)} tracks from selected artists")
    
    # STEP 4: Combine all sources and remove duplicates
    all_candidates = rec_tracks + search_tracks + artist_tracks
    candidate_uris = list(dict.fromkeys(all_candidates))  # Remove duplicates, preserve order
    
    print(f"[Recommend] Total unique candidates: {len(candidate_uris)}")
    
    if not candidate_uris:
        print("[Recommend] WARNING: No candidates found!")
        return []
    
    # STEP 5: Fetch audio features for all candidates
    features_map = _fetch_audio_features(sp, candidate_uris)
    
    # STEP 6: Score each track by vibe match (with artist boost)
    scored_tracks = []
    for uri in candidate_uris:
        track_id = uri.split(":")[-1]
        features = features_map.get(track_id)
        
        # If no features available, give neutral score
        if not features:
            base_score = 0.5
        else:
            # Calculate vibe match score (0-1, higher is better)
            base_score = _calculate_vibe_score(
                features,
                target_energy=target_energy,
                target_valence=target_valence,
                target_danceability=target_danceability,
                target_acousticness=target_acousticness,
                target_tempo=tempo_bpm,
            )
        
        # BOOST SCORE for selected artists (so they appear prominently)
        final_score = base_score
        if user_artist_ids:
            # Check if this track is from a selected artist
            # We'll verify this in the diversity step, but boost here too
            artist_tracks_set = set(artist_tracks)
            if uri in artist_tracks_set:
                # Boost by 0.15 (significant but not overwhelming)
                final_score = min(1.0, base_score + 0.15)
                print(f"[Score] Boosted artist track: {uri.split(':')[-1]} from {base_score:.2f} to {final_score:.2f}")
        
        scored_tracks.append((uri, final_score, features))
    
    # Sort by score (best first)
    scored_tracks.sort(key=lambda x: x[1], reverse=True)
    print(f"[Recommend] Top 5 scores: {[round(s, 2) for _, s, _ in scored_tracks[:5]]}")
    
    # STEP 7: Apply diversity rules with artist priority
    final_uris = _apply_diversity(sp, scored_tracks, n, user_artist_ids)
    
    print(f"[Recommend] Returning {len(final_uris)} tracks")
    
    # STEP 8: VERIFY selected artists are included
    if user_artist_ids and not only_selected_artists:
        artist_count = _count_artist_tracks_in_results(sp, final_uris, user_artist_ids)
        print(f"[Recommend] Selected artists appear {artist_count} times in final results")
        
        if artist_count == 0:
            print(f"[Recommend] WARNING: No tracks from selected artists in results! Forcing inclusion...")
            # Force include at least 3 tracks from selected artists
            final_uris = _force_artist_inclusion(sp, scored_tracks, final_uris, user_artist_ids, min_count=3)
    
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


def _intelligent_search(
    sp: Spotify,
    vibe_params: dict,
    genres: List[str],
    user_artist_ids: Optional[List[str]],
    limit: int = 100
) -> List[str]:
    """
    Intelligently search for tracks matching the vibe.
    Uses multiple search strategies to cast a wide net.
    
    This is now the PRIMARY method for finding tracks, not a fallback.
    """
    tracks = []
    seen_uris = set()
    
    # Extract vibe parameters
    mood = vibe_params.get('mood', '')
    keywords = vibe_params.get('keywords', [])
    scene = vibe_params.get('scene', '')
    energy_range = vibe_params.get('energy_range', [0.5, 0.7])
    
    # Determine energy level descriptor
    avg_energy = sum(energy_range) / 2
    if avg_energy > 0.7:
        energy_word = "energetic"
    elif avg_energy < 0.4:
        energy_word = "chill"
    else:
        energy_word = "moderate"
    
    print(f"[Search] Building queries for mood='{mood}', energy={energy_word}, keywords={keywords}")
    
    # STRATEGY 1: Genre + Mood combinations
    if genres:
        for genre in genres[:3]:  # Top 3 genres
            queries = [
                f"{genre} {mood}",
                f"{genre} {energy_word}",
                f"{genre} {scene}" if scene else None,
            ]
            for query in queries:
                if query and len(tracks) < limit:
                    found = _search_spotify(sp, query.strip(), seen_uris, max_tracks=20)
                    tracks.extend(found)
                    print(f"[Search] Query '{query}' found {len(found)} tracks")
    
    # STRATEGY 2: Mood + Keywords combinations
    if mood and keywords:
        query = f"{mood} {' '.join(keywords[:2])}"
        if len(tracks) < limit:
            found = _search_spotify(sp, query, seen_uris, max_tracks=20)
            tracks.extend(found)
            print(f"[Search] Query '{query}' found {len(found)} tracks")
    
    # STRATEGY 3: Scene-based search
    if scene and len(tracks) < limit:
        queries = [
            scene,
            f"{scene} music",
            f"{energy_word} {scene}",
        ]
        for query in queries:
            if len(tracks) < limit:
                found = _search_spotify(sp, query, seen_uris, max_tracks=15)
                tracks.extend(found)
                print(f"[Search] Query '{query}' found {len(found)} tracks")
    
    # STRATEGY 4: Pure mood/keyword search
    if len(tracks) < limit and keywords:
        for keyword in keywords[:3]:
            if len(tracks) < limit:
                found = _search_spotify(sp, keyword, seen_uris, max_tracks=15)
                tracks.extend(found)
                print(f"[Search] Query '{keyword}' found {len(found)} tracks")
    
    # STRATEGY 5: Related artists (if user selected specific artists)
    if user_artist_ids and len(tracks) < limit:
        print(f"[Search] Searching related artists...")
        related_tracks = _search_related_artists(sp, user_artist_ids, seen_uris, max_tracks=30)
        tracks.extend(related_tracks)
        print(f"[Search] Related artists found {len(related_tracks)} tracks")
    
    # STRATEGY 6: Playlist mining (search for playlists matching the vibe)
    if len(tracks) < limit:
        print(f"[Search] Mining playlists...")
        playlist_query = f"{mood} {' '.join(genres[:2])}" if genres else mood
        playlist_tracks = _mine_playlists(sp, playlist_query, seen_uris, max_tracks=30)
        tracks.extend(playlist_tracks)
        print(f"[Search] Playlist mining found {len(playlist_tracks)} tracks")
    
    # STRATEGY 7: Fallback to genre-only if we're still short
    if len(tracks) < limit // 2:  # If we have less than half needed
        print(f"[Search] Running fallback genre search...")
        for genre in genres[:2]:
            if len(tracks) < limit:
                found = _search_spotify(sp, f"genre:{genre}", seen_uris, max_tracks=30)
                tracks.extend(found)
    
    print(f"[Search] Total tracks found: {len(tracks)}")
    return tracks[:limit]


def _search_spotify(sp: Spotify, query: str, seen_uris: set, max_tracks: int = 20) -> List[str]:
    """
    Execute a single Spotify search query and return unique track URIs.
    """
    if not query or not query.strip():
        return []
    
    try:
        result = sp.search(q=query, type='track', limit=max_tracks, market='US')
        tracks = []
        for track in result.get('tracks', {}).get('items', []):
            if track and track.get('uri'):
                uri = track['uri']
                if uri not in seen_uris:
                    tracks.append(uri)
                    seen_uris.add(uri)
        return tracks
    except Exception as e:
        print(f"[Search] Query '{query}' failed: {e}")
        return []


def _search_related_artists(sp: Spotify, artist_ids: List[str], seen_uris: set, max_tracks: int = 30) -> List[str]:
    """
    Find tracks from artists related to the user's selected artists.
    """
    tracks = []
    for artist_id in artist_ids[:2]:  # Limit to first 2 artists
        try:
            # Get related artists
            result = sp.artist_related_artists(artist_id)
            related = result.get('artists', [])[:5]  # Top 5 related
            
            # Get top tracks from each related artist
            for related_artist in related:
                if len(tracks) >= max_tracks:
                    break
                try:
                    top_tracks = sp.artist_top_tracks(related_artist['id'], country='US')
                    for track in top_tracks.get('tracks', [])[:3]:  # Top 3 from each
                        if track.get('uri'):
                            uri = track['uri']
                            if uri not in seen_uris:
                                tracks.append(uri)
                                seen_uris.add(uri)
                except:
                    continue
        except Exception as e:
            print(f"[Search] Related artists search failed for {artist_id}: {e}")
            continue
    
    return tracks


def _mine_playlists(sp: Spotify, query: str, seen_uris: set, max_tracks: int = 30) -> List[str]:
    """
    Search for playlists matching the vibe and extract their tracks.
    """
    tracks = []
    try:
        # Search for playlists
        result = sp.search(q=query, type='playlist', limit=3)  # Top 3 playlists
        playlists = result.get('playlists', {}).get('items', [])
        
        for playlist in playlists:
            if len(tracks) >= max_tracks:
                break
            
            try:
                # Get playlist tracks
                playlist_id = playlist['id']
                playlist_tracks = sp.playlist_tracks(playlist_id, limit=20)
                
                for item in playlist_tracks.get('items', []):
                    if len(tracks) >= max_tracks:
                        break
                    
                    track = item.get('track')
                    if track and track.get('uri'):
                        uri = track['uri']
                        if uri not in seen_uris:
                            tracks.append(uri)
                            seen_uris.add(uri)
            except:
                continue
                
    except Exception as e:
        print(f"[Search] Playlist mining failed: {e}")
    
    return tracks


def _get_artist_tracks(sp: Spotify, artist_ids: List[str], max_per_artist: int = 15) -> List[str]:
    """
    Get tracks from selected artists.
    Now includes top tracks AND album deep cuts for better variety.
    
    NOTE: This is the lighter version. For extensive catalog, use _get_artist_extensive_catalog.
    """
    tracks = []
    for artist_id in artist_ids[:5]:  # Max 5 artists
        artist_tracks = []
        
        try:
            # Get top tracks (most popular)
            result = sp.artist_top_tracks(artist_id, country="US")
            for track in result.get("tracks", [])[:8]:  # Top 8 tracks
                if track.get("uri"):
                    artist_tracks.append(track["uri"])
        except Exception as e:
            print(f"[Artist] Failed to get top tracks for {artist_id}: {e}")
        
        # Also get some album tracks for deeper cuts
        try:
            albums = sp.artist_albums(artist_id, limit=5, album_type='album')
            for album in albums.get('items', [])[:3]:  # Top 3 albums
                album_tracks = sp.album_tracks(album['id'], limit=10)
                for track in album_tracks.get('items', [])[:3]:  # 3 tracks per album
                    if track.get('uri'):
                        artist_tracks.append(track['uri'])
                        if len(artist_tracks) >= max_per_artist:
                            break
                if len(artist_tracks) >= max_per_artist:
                    break
        except Exception as e:
            print(f"[Artist] Failed to get album tracks for {artist_id}: {e}")
        
        tracks.extend(artist_tracks[:max_per_artist])
    
    return tracks


def _get_artist_extensive_catalog(sp: Spotify, artist_ids: List[str], max_per_artist: int = 50) -> List[str]:
    """
    Get EXTENSIVE tracks from selected artists for "only artist" mode or heavy inclusion.
    Searches deeper into their catalog for variety.
    """
    tracks = []
    
    for artist_id in artist_ids[:5]:  # Max 5 artists
        artist_tracks = []
        
        try:
            # Get artist name for logging
            artist_info = sp.artist(artist_id)
            artist_name = artist_info.get('name', artist_id)
            print(f"[Artist] Fetching extensive catalog for {artist_name}...")
            
            # 1. Top tracks (always good)
            result = sp.artist_top_tracks(artist_id, country="US")
            for track in result.get("tracks", []):
                if track.get("uri"):
                    artist_tracks.append(track["uri"])
            
            # 2. Recent albums (singles, albums, compilations)
            albums_result = sp.artist_albums(
                artist_id, 
                limit=20,  # Get more albums
                album_type='album,single,compilation'
            )
            
            for album in albums_result.get('items', []):
                if len(artist_tracks) >= max_per_artist:
                    break
                
                try:
                    # Get tracks from this album
                    album_tracks = sp.album_tracks(album['id'], limit=50)
                    for track in album_tracks.get('items', []):
                        if track.get('uri'):
                            artist_tracks.append(track['uri'])
                            if len(artist_tracks) >= max_per_artist:
                                break
                except:
                    continue
            
            # Remove duplicates
            artist_tracks = list(dict.fromkeys(artist_tracks))
            
            print(f"[Artist] Got {len(artist_tracks)} tracks from {artist_name}")
            tracks.extend(artist_tracks[:max_per_artist])
            
        except Exception as e:
            print(f"[Artist] Failed to get extensive catalog for {artist_id}: {e}")
    
    return tracks


def _count_artist_tracks_in_results(sp: Spotify, track_uris: List[str], artist_ids: List[str]) -> int:
    """
    Count how many tracks in the results are from the selected artists.
    """
    if not track_uris or not artist_ids:
        return 0
    
    count = 0
    artist_ids_set = set(artist_ids)
    
    try:
        # Get track info
        track_ids = [uri.split(":")[-1] for uri in track_uris[:50]]  # Limit for performance
        result = sp.tracks(track_ids)
        
        for track in result.get("tracks", []):
            if not track:
                continue
            
            # Check if any of the track's artists match selected artists
            track_artist_ids = [a["id"] for a in track.get("artists", [])]
            if any(aid in artist_ids_set for aid in track_artist_ids):
                count += 1
    
    except Exception as e:
        print(f"[Artist] Failed to count artist tracks: {e}")
    
    return count


def _force_artist_inclusion(
    sp: Spotify,
    scored_tracks: List[tuple],
    current_results: List[str],
    artist_ids: List[str],
    min_count: int = 3
) -> List[str]:
    """
    Ensure at least min_count tracks from selected artists appear in results.
    If not enough, replace lowest-scoring non-artist tracks with artist tracks.
    """
    # Find tracks from selected artists in scored list
    artist_ids_set = set(artist_ids)
    artist_tracks_scored = []
    non_artist_tracks_in_results = []
    
    # Get track info to identify which are from selected artists
    try:
        result_track_ids = [uri.split(":")[-1] for uri in current_results]
        result_tracks_info = sp.tracks(result_track_ids[:50])
        
        # Build map of which results are from selected artists
        result_artist_map = {}
        for track in result_tracks_info.get("tracks", []):
            if not track:
                continue
            uri = track["uri"]
            track_artist_ids = [a["id"] for a in track.get("artists", [])]
            is_from_selected = any(aid in artist_ids_set for aid in track_artist_ids)
            result_artist_map[uri] = is_from_selected
            
            if not is_from_selected:
                non_artist_tracks_in_results.append(uri)
        
        # Count current artist tracks
        current_artist_count = sum(1 for is_artist in result_artist_map.values() if is_artist)
        
        if current_artist_count >= min_count:
            return current_results  # Already have enough
        
        needed = min_count - current_artist_count
        print(f"[Artist] Need to add {needed} more tracks from selected artists")
        
        # Find high-scoring artist tracks not yet in results
        for uri, score, features in scored_tracks:
            if uri in current_results:
                continue
            
            # Check if from selected artist
            track_id = uri.split(":")[-1]
            try:
                track_info = sp.track(track_id)
                track_artist_ids = [a["id"] for a in track_info.get("artists", [])]
                if any(aid in artist_ids_set for aid in track_artist_ids):
                    artist_tracks_scored.append((uri, score))
            except:
                continue
        
        # Replace lowest-scoring non-artist tracks with highest-scoring artist tracks
        # Sort artist tracks by score (best first)
        artist_tracks_scored.sort(key=lambda x: x[1], reverse=True)
        
        new_results = list(current_results)
        replacements_made = 0
        
        for artist_uri, artist_score in artist_tracks_scored[:needed]:
            if replacements_made >= needed:
                break
            
            # Remove the last non-artist track (lowest position)
            if non_artist_tracks_in_results:
                removed_uri = non_artist_tracks_in_results.pop()
                idx = new_results.index(removed_uri)
                new_results[idx] = artist_uri
                replacements_made += 1
                print(f"[Artist] Replaced track with artist track (score {artist_score:.2f})")
        
        return new_results
        
    except Exception as e:
        print(f"[Artist] Failed to force artist inclusion: {e}")
        return current_results


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