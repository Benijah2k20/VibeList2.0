# backend/catalog_builder_v3.py
"""
VibeList Catalog Builder V3 - Genre-Based Artist Discovery

NEW STRATEGY:
- Get top 50 artists from each major genre
- Download their ENTIRE discographies
- Target: 10,000 high-quality tracks
- Better coverage than random playlists

Usage:
    python3 catalog_builder_v3.py
"""
import os
import sys
import requests
import time
import librosa
import numpy as np
import deezer
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Set
from collections import defaultdict

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

# Spotify auth
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Preview cache
PREVIEW_CACHE = Path(__file__).parent / "preview_cache"
PREVIEW_CACHE.mkdir(exist_ok=True)

# Database
DB_PATH = Path(__file__).parent / "vibelist.db"

# Initialize clients
deezer_client = deezer.Client()

# Progress tracking
PROGRESS_FILE = Path(__file__).parent / "catalog_v3_progress.json"


# ============================================================================
# GENRE-BASED ARTIST DISCOVERY
# ============================================================================

def get_top_artists_by_genre(sp, genre: str, limit: int = 50) -> List[str]:
    """
    Get top artists for a specific genre.
    
    Strategy:
    1. Search for top playlists in this genre
    2. Extract artists from those playlists
    3. Rank by frequency (most common = most popular)
    4. Return top N artist IDs
    """
    print(f"\n[{genre.upper()}] Finding top artists...")
    
    artist_frequency = defaultdict(int)
    artist_names = {}
    
    try:
        # Search for curated playlists in this genre
        search_terms = [
            f"top {genre}",
            f"best {genre}",
            f"{genre} hits",
            f"{genre} essentials",
            f"popular {genre}"
        ]
        
        for search_term in search_terms:
            try:
                result = sp.search(q=search_term, type='playlist', limit=10)
                playlists = result.get('playlists', {}).get('items', [])
                
                for playlist in playlists:
                    try:
                        # Get tracks from this playlist
                        tracks_result = sp.playlist_tracks(playlist['id'], limit=100)
                        
                        for item in tracks_result.get('items', []):
                            track = item.get('track')
                            if not track or not track.get('artists'):
                                continue
                            
                            # Count each artist
                            for artist in track['artists']:
                                artist_id = artist['id']
                                artist_frequency[artist_id] += 1
                                artist_names[artist_id] = artist['name']
                        
                        time.sleep(0.1)  # Rate limit
                    except:
                        continue
                
                time.sleep(0.2)
            except:
                continue
        
        # Sort by frequency (most popular first)
        sorted_artists = sorted(
            artist_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        top_artists = [artist_id for artist_id, _ in sorted_artists[:limit]]
        
        print(f"[{genre.upper()}] Found {len(top_artists)} top artists")
        for i, artist_id in enumerate(top_artists[:10]):
            name = artist_names.get(artist_id, "Unknown")
            freq = artist_frequency[artist_id]
            print(f"  {i+1}. {name} (appeared {freq} times)")
        
        return top_artists
        
    except Exception as e:
        print(f"[{genre.upper()}] Error: {e}")
        return []


def get_artist_discography(sp, artist_id: str, artist_name: str = None) -> List[Dict]:
    """
    Get ALL tracks from an artist's discography.
    
    Returns:
        List of track dicts with Spotify metadata
    """
    if not artist_name:
        try:
            artist_info = sp.artist(artist_id)
            artist_name = artist_info.get('name', artist_id)
        except:
            artist_name = artist_id
    
    print(f"\n[Artist] Fetching discography for {artist_name}...")
    
    tracks = []
    seen_track_ids = set()
    
    try:
        # Get ALL albums (albums, singles, compilations)
        albums = []
        offset = 0
        
        while True:
            try:
                result = sp.artist_albums(
                    artist_id,
                    album_type='album,single,compilation',
                    limit=50,
                    offset=offset
                )
                
                items = result.get('items', [])
                if not items:
                    break
                
                albums.extend(items)
                offset += 50
                
                if not result.get('next'):
                    break
                
                time.sleep(0.1)
            except:
                break
        
        print(f"[Artist]   Found {len(albums)} albums/singles")
        
        # Get tracks from each album
        for album in albums:
            try:
                album_tracks = sp.album_tracks(album['id'], limit=50)
                
                for track in album_tracks.get('items', []):
                    track_id = track.get('id')
                    if not track_id or track_id in seen_track_ids:
                        continue
                    
                    seen_track_ids.add(track_id)
                    
                    tracks.append({
                        'spotify_id': track_id,
                        'spotify_uri': track['uri'],
                        'name': track['name'],
                        'artists': [a['name'] for a in track.get('artists', [])],
                        'album': album.get('name', ''),
                        'popularity': album.get('popularity', 0),  # Use album popularity
                    })
                
                time.sleep(0.1)
            except:
                continue
        
        print(f"[Artist]   Got {len(tracks)} tracks from {artist_name}")
        return tracks
        
    except Exception as e:
        print(f"[Artist]   Error: {e}")
        return []


def build_genre_based_catalog(sp, target_tracks: int = 10000) -> List[Dict]:
    """
    Build catalog by getting top artists from each genre.
    
    Args:
        sp: Spotify client
        target_tracks: Target number of tracks (default 10,000)
    
    Returns:
        List of track dicts
    """
    print(f"\n{'='*70}")
    print(f"CATALOG BUILDER V3 - GENRE-BASED ARTIST DISCOVERY")
    print(f"Target: {target_tracks} tracks")
    print(f"{'='*70}\n")
    
    # Major genres to cover
    genres = [
        'pop',
        'hip-hop',
        'rap',
        'r-n-b',
        'rock',
        'alternative',
        'indie',
        'electronic',
        'dance',
        'latin',
        'reggaeton',
        'country',
        'soul',
        'funk',
    ]
    
    all_tracks = []
    seen_track_ids = set()
    
    # Calculate how many artists per genre
    artists_per_genre = 50  # Top 50 artists per genre
    
    for genre in genres:
        if len(all_tracks) >= target_tracks:
            print(f"\n✓ Reached target of {target_tracks} tracks!")
            break
        
        print(f"\n{'='*70}")
        print(f"GENRE: {genre.upper()}")
        print(f"Progress: {len(all_tracks)}/{target_tracks} tracks")
        print(f"{'='*70}")
        
        # Get top artists for this genre
        artist_ids = get_top_artists_by_genre(sp, genre, limit=artists_per_genre)
        
        if not artist_ids:
            print(f"[{genre}] No artists found, skipping...")
            continue
        
        # Get discography for each artist
        for i, artist_id in enumerate(artist_ids):
            if len(all_tracks) >= target_tracks:
                break
            
            print(f"\n[{genre}] Artist {i+1}/{len(artist_ids)}")
            
            artist_tracks = get_artist_discography(sp, artist_id)
            
            # Add unique tracks
            for track in artist_tracks:
                if track['spotify_id'] not in seen_track_ids:
                    seen_track_ids.add(track['spotify_id'])
                    all_tracks.append(track)
            
            print(f"[Progress] Total: {len(all_tracks)}/{target_tracks} tracks")
            
            # Save progress every 100 tracks
            if len(all_tracks) % 100 == 0:
                save_progress(all_tracks, genre, i)
        
        print(f"\n[{genre}] Completed! Added {len(artist_tracks)} tracks")
    
    print(f"\n{'='*70}")
    print(f"DISCOVERY COMPLETE!")
    print(f"Total tracks: {len(all_tracks)}")
    print(f"{'='*70}\n")
    
    return all_tracks


def save_progress(tracks: List[Dict], current_genre: str, current_artist_idx: int):
    """Save progress to resume later if needed."""
    import json
    
    progress = {
        'total_tracks': len(tracks),
        'current_genre': current_genre,
        'current_artist_idx': current_artist_idx,
        'timestamp': time.time()
    }
    
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


# ============================================================================
# DEEZER MATCHING & AUDIO ANALYSIS
# ============================================================================

def find_deezer_match(track_name: str, artist_name: str, retries: int = 3) -> Optional[dict]:
    """
    Find matching track on Deezer with retry logic.
    
    Uses 3-stage fallback:
    1. Exact match (track + artist)
    2. Track name only
    3. Artist name only (get popular tracks)
    """
    for attempt in range(retries):
        try:
            # Stage 1: Exact match
            query = f"{track_name} {artist_name}"
            results = deezer_client.search(query)
            
            if results:
                # Find best match
                for result in results:
                    result_title = result.title.lower()
                    result_artist = result.artist.name.lower()
                    track_lower = track_name.lower()
                    artist_lower = artist_name.lower()
                    
                    # Check if it's a good match
                    if (track_lower in result_title or result_title in track_lower) and \
                       (artist_lower in result_artist or result_artist in artist_lower):
                        return {
                            'id': result.id,
                            'preview': result.preview,
                            'duration': result.duration
                        }
            
            # Stage 2: Track name only
            results = deezer_client.search(track_name)
            if results and len(results) > 0:
                first_result = results[0]
                return {
                    'id': first_result.id,
                    'preview': first_result.preview,
                    'duration': first_result.duration
                }
            
            time.sleep(0.2 * (attempt + 1))  # Exponential backoff
            
        except Exception as e:
            if attempt == retries - 1:
                print(f"[Deezer] Failed to find: {track_name} - {artist_name}")
            time.sleep(0.5 * (attempt + 1))
    
    return None


def download_preview(preview_url: str, cache_path: Path) -> bool:
    """Download preview audio file."""
    try:
        response = requests.get(preview_url, timeout=10)
        response.raise_for_status()
        
        with open(cache_path, 'wb') as f:
            f.write(response.content)
        
        return True
    except Exception as e:
        print(f"[Download] Error: {e}")
        return False


def analyze_audio(file_path: Path) -> Optional[Dict]:
    """
    Analyze audio file using librosa.
    
    Returns dict with audio features or None if failed.
    """
    try:
        # Load audio
        y, sr = librosa.load(str(file_path), duration=30, sr=22050)
        
        # Extract features
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        
        # Spectral features
        spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
        
        # RMS energy
        rms = librosa.feature.rms(y=y)[0]
        
        # Zero crossing rate
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        
        # MFCC
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        
        # Calculate features
        energy = float(np.mean(rms))
        tempo_val = float(tempo)
        
        # Normalize features to 0-1 range
        # These mappings are approximate and can be tuned
        features = {
            'tempo': tempo_val,
            'energy': min(1.0, energy * 2),  # Rough normalization
            'danceability': min(1.0, (energy + np.mean(zcr)) / 2),
            'valence': min(1.0, np.mean(spectral_centroids) / 4000),
            'acousticness': max(0.0, 1.0 - (np.mean(spectral_rolloff) / 8000)),
            'speechiness': min(1.0, np.mean(mfccs[0]) / 50),
            'instrumentalness': 0.5,  # Hard to detect without ML model
            'liveness': 0.1,  # Hard to detect without ML model
            'loudness': float(20 * np.log10(np.mean(rms) + 1e-10)),
            'key': 0,  # Requires additional analysis
            'mode': 1,  # Requires additional analysis
            'time_signature': 4,  # Assume 4/4
        }
        
        return features
        
    except Exception as e:
        print(f"[Analysis] Error: {e}")
        return None


def process_track(track: Dict) -> Optional[Dict]:
    """
    Full pipeline: Find on Deezer → Download → Analyze → Return features.
    
    Returns dict with track info + features, or None if failed.
    """
    track_name = track['name']
    artist_name = track['artists'][0] if track['artists'] else "Unknown"
    
    # Find on Deezer
    deezer_match = find_deezer_match(track_name, artist_name)
    if not deezer_match or not deezer_match.get('preview'):
        return None
    
    # Download preview
    preview_url = deezer_match['preview']
    cache_file = PREVIEW_CACHE / f"{track['spotify_id']}.mp3"
    
    if not cache_file.exists():
        if not download_preview(preview_url, cache_file):
            return None
    
    # Analyze audio
    features = analyze_audio(cache_file)
    if not features:
        # Clean up failed file
        if cache_file.exists():
            cache_file.unlink()
        return None
    
    # Combine track info + features
    result = {
        **track,
        **features,
        'deezer_preview_url': preview_url
    }
    
    # Clean up cache file to save space
    if cache_file.exists():
        cache_file.unlink()
    
    return result


def save_to_database(tracks: List[Dict]):
    """Save analyzed tracks to database."""
    print(f"\n[Database] Saving {len(tracks)} tracks...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create table if doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS track_catalog (
            track_id TEXT PRIMARY KEY,
            track_uri TEXT NOT NULL,
            track_name TEXT NOT NULL,
            artists TEXT NOT NULL,
            album TEXT,
            popularity INTEGER,
            tempo REAL,
            energy REAL,
            danceability REAL,
            valence REAL,
            acousticness REAL,
            speechiness REAL,
            instrumentalness REAL,
            liveness REAL,
            loudness REAL,
            key INTEGER,
            mode INTEGER,
            time_signature INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    success_count = 0
    for track in tracks:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO track_catalog VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                track['spotify_id'],
                track['spotify_uri'],
                track['name'],
                ','.join(track['artists']),
                track.get('album', ''),
                track.get('popularity', 0),
                track.get('tempo', 120),
                track.get('energy', 0.5),
                track.get('danceability', 0.5),
                track.get('valence', 0.5),
                track.get('acousticness', 0.5),
                track.get('speechiness', 0.05),
                track.get('instrumentalness', 0.0),
                track.get('liveness', 0.1),
                track.get('loudness', -5.0),
                track.get('key', 0),
                track.get('mode', 1),
                track.get('time_signature', 4),
            ))
            success_count += 1
        except Exception as e:
            print(f"[Database] Failed to save {track['name']}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"[Database] ✓ Saved {success_count}/{len(tracks)} tracks")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution flow."""
    print("\n" + "="*70)
    print("VIBELIST CATALOG BUILDER V3")
    print("Genre-Based Artist Discovery")
    print("="*70 + "\n")
    
    # Load environment variables from .env file
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Loaded credentials from {env_path}")
    else:
        print(f"⚠️  No .env file found at {env_path}")
    
    # Initialize Spotify client
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ Error: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET not found!")
        print("\nMake sure your .env file contains:")
        print("SPOTIFY_CLIENT_ID=your_id")
        print("SPOTIFY_CLIENT_SECRET=your_secret")
        return
    
    auth_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    
    # Step 1: Discover tracks (10,000 target)
    print("\n[Step 1] Discovering tracks from top artists by genre...")
    tracks = build_genre_based_catalog(sp, target_tracks=10000)
    
    if not tracks:
        print("❌ No tracks discovered!")
        return
    
    print(f"\n✓ Discovered {len(tracks)} tracks")
    
    # Step 2: Analyze tracks
    print(f"\n[Step 2] Analyzing {len(tracks)} tracks...")
    print("This will take a while... Grab a coffee! ☕\n")
    
    analyzed_tracks = []
    failed_count = 0
    
    for i, track in enumerate(tracks):
        print(f"\n[{i+1}/{len(tracks)}] {track['name']} - {track['artists'][0] if track['artists'] else 'Unknown'}")
        
        result = process_track(track)
        
        if result:
            analyzed_tracks.append(result)
            print(f"  ✓ Success! ({len(analyzed_tracks)} analyzed so far)")
        else:
            failed_count += 1
            print(f"  ✗ Failed ({failed_count} failures)")
        
        # Save progress every 100 tracks
        if len(analyzed_tracks) % 100 == 0 and len(analyzed_tracks) > 0:
            print(f"\n[Checkpoint] Saving {len(analyzed_tracks)} tracks to database...")
            save_to_database(analyzed_tracks)
            analyzed_tracks = []  # Clear to save memory
        
        # Rate limiting
        time.sleep(0.2)
    
    # Save remaining tracks
    if analyzed_tracks:
        save_to_database(analyzed_tracks)
    
    # Final stats
    print("\n" + "="*70)
    print("CATALOG BUILD COMPLETE!")
    print("="*70)
    print(f"Total tracks discovered: {len(tracks)}")
    print(f"Successfully analyzed: {len(tracks) - failed_count}")
    print(f"Failed: {failed_count}")
    print(f"Success rate: {((len(tracks) - failed_count) / len(tracks)) * 100:.1f}%")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
