# backend/catalog_builder_v2.py
"""
VibeList Catalog Builder V2 - IMPROVED!

Improvements over V1:
- Retry logic with exponential backoff
- 3-stage fallback matching strategy
- Resume capability (skip already-analyzed tracks)
- Better rate limiting
- Progress tracking and auto-save
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
from typing import List, Dict, Optional

# Preview cache directory
PREVIEW_CACHE = Path(__file__).parent / "preview_cache"
PREVIEW_CACHE.mkdir(exist_ok=True)

# Initialize Deezer client
deezer_client = deezer.Client()

# Progress tracking
PROGRESS_FILE = Path(__file__).parent / "catalog_progress.txt"


# ============================================================================
# SPOTIFY TRACK DISCOVERY
# ============================================================================

def get_popular_tracks_spotify(sp, limit: int = 1000, offset: int = 0) -> List[dict]:
    """
    Get popular tracks from Spotify using search.
    Can resume from an offset to avoid re-fetching.
    """
    print(f"\n[Spotify] Fetching tracks (offset={offset}, limit={limit})...")
    
    tracks = []
    seen_ids = set()
    
    # Expanded artist list for more variety
    search_queries = [
        # Pop
        "Drake", "Taylor Swift", "The Weeknd", "Ariana Grande",
        "Post Malone", "Billie Eilish", "Ed Sheeran", "Dua Lipa",
        "Harry Styles", "Olivia Rodrigo", "Sabrina Carpenter", "Chappell Roan",
        
        # Hip-Hop/Rap
        "Kendrick Lamar", "J. Cole", "Travis Scott", "21 Savage",
        "Lil Baby", "Future", "Metro Boomin", "Baby Keem",
        
        # Latin
        "Bad Bunny", "Karol G", "Peso Pluma", "Feid",
        
        # R&B
        "SZA", "Brent Faiyaz", "Summer Walker", "Bryson Tiller",
        
        # Electronic/Dance
        "Calvin Harris", "The Chainsmokers", "Marshmello", "Kygo",
        
        # Rock/Alternative
        "Imagine Dragons", "Twenty One Pilots", "Arctic Monkeys", "The 1975",
    ]
    
    query_count = 0
    for query in search_queries:
        if len(tracks) >= limit:
            break
        
        # Skip queries if we're resuming from an offset
        if query_count * 50 < offset:
            query_count += 1
            continue
        
        try:
            result = sp.search(q=query, type="track", limit=50)
            
            for item in result.get("tracks", {}).get("items", []):
                if len(tracks) >= limit:
                    break
                
                track = item
                if not track or track.get("id") in seen_ids:
                    continue
                
                seen_ids.add(track["id"])
                
                tracks.append({
                    "spotify_id": track["id"],
                    "spotify_uri": track["uri"],
                    "name": track["name"],
                    "artists": [a["name"] for a in track.get("artists", [])],
                    "album": track.get("album", {}).get("name", ""),
                    "popularity": track.get("popularity", 0),
                })
            
            if (len(seen_ids) % 100) == 0:
                print(f"[Spotify] Progress: {len(seen_ids)} tracks collected...")
            
            time.sleep(0.3)  # Rate limiting
            query_count += 1
            
        except Exception as e:
            print(f"[Spotify] Error on '{query}': {e}")
            continue
    
    print(f"[Spotify] ✓ Collected {len(tracks)} tracks\n")
    return tracks


# ============================================================================
# DEEZER PREVIEW DISCOVERY - WITH SMART FALLBACKS
# ============================================================================

def find_deezer_match_v2(track_name: str, artist_name: str, max_retries: int = 3) -> Optional[str]:
    """
    Find matching track on Deezer with 3-stage fallback strategy and retry logic.
    
    Strategy 1: Full match (artist + full track name)
    Strategy 2: Clean match (remove featuring/remix tags)
    Strategy 3: Artist fallback (any popular track by artist)
    """
    
    # STRATEGY 1: Try full match
    for attempt in range(max_retries):
        try:
            time.sleep(0.5)  # Rate limiting
            
            query = f"{artist_name} {track_name}"
            results = deezer_client.search(query)
            
            if results and len(results) > 0:
                # Check first 3 results for exact match
                for result in results[:3]:
                    if hasattr(result, 'preview') and result.preview:
                        return result.preview
            
            # Success but no preview
            break
            
        except Exception as e:
            if "getaddrinfo failed" in str(e) or "timeout" in str(e).lower():
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"  [Retry {attempt+1}/{max_retries}] Network error, waiting {wait}s...")
                    time.sleep(wait)
                    continue
            break
    
    # STRATEGY 2: Clean match (remove features, remixes, etc.)
    try:
        time.sleep(0.5)
        
        # Clean the track name
        clean_name = track_name.split('(feat')[0].split('(with')[0].split('-')[0].strip()
        
        if clean_name != track_name:  # Only try if we actually cleaned something
            query = f"{artist_name} {clean_name}"
            results = deezer_client.search(query)
            
            if results and len(results) > 0:
                for result in results[:3]:
                    if hasattr(result, 'preview') and result.preview:
                        return result.preview
    except:
        pass
    
    # STRATEGY 3: Artist fallback (get ANY popular track by this artist)
    try:
        time.sleep(0.5)
        
        results = deezer_client.search(artist_name)
        
        if results and len(results) > 0:
            # Get the most popular track with preview
            for result in results[:5]:
                if hasattr(result, 'preview') and result.preview:
                    return result.preview
    except:
        pass
    
    return None


def download_preview_deezer(preview_url: str, track_id: str) -> Optional[Path]:
    """Download 30-second preview MP3 from Deezer with retry logic."""
    output_path = PREVIEW_CACHE / f"{track_id}.mp3"
    
    # Skip if already downloaded
    if output_path.exists():
        return output_path
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(preview_url, timeout=15)
            response.raise_for_status()
            
            with open(output_path, "wb") as f:
                f.write(response.content)
            
            return output_path
            
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [Retry download {attempt+1}/{max_retries}] {e}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Download failed after {max_retries} attempts: {e}")
                return None
    
    return None


# ============================================================================
# AUDIO ANALYSIS (Same as V1)
# ============================================================================

def analyze_audio(audio_path: Path) -> Optional[Dict]:
    """Extract audio features using Librosa."""
    try:
        y, sr = librosa.load(audio_path, duration=30, sr=22050)
        
        # Tempo & rhythm
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        
        # Energy
        rms = librosa.feature.rms(y=y)[0]
        energy = float(np.mean(rms) / np.max(rms) if np.max(rms) > 0 else 0.5)
        
        # Danceability
        danceability = estimate_danceability(beats, len(y), sr)
        
        # Valence
        spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
        valence = estimate_valence(spectral_centroids, spectral_rolloff)
        
        # Acousticness
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        acousticness = estimate_acousticness(mfccs, spectral_centroids)
        
        # Speechiness
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        speechiness = float(np.clip(np.mean(zcr), 0, 1))
        
        # Key
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        key = int(np.argmax(np.mean(chroma, axis=1)))
        
        # Loudness
        loudness = float(20 * np.log10(np.mean(rms)) if np.mean(rms) > 0 else -60)
        
        features = {
            "tempo": float(tempo),
            "energy": energy,
            "danceability": danceability,
            "valence": valence,
            "acousticness": acousticness,
            "speechiness": speechiness,
            "instrumentalness": 0.5,
            "liveness": 0.2,
            "loudness": loudness,
            "key": key,
            "mode": 1,
            "time_signature": 4,
        }
        
        return features
        
    except Exception as e:
        return None


def estimate_danceability(beats, total_samples, sr) -> float:
    try:
        if len(beats) < 2:
            return 0.5
        beat_times = librosa.frames_to_time(beats, sr=sr)
        intervals = np.diff(beat_times)
        regularity = 1.0 - np.std(intervals) / (np.mean(intervals) + 0.001)
        return float(np.clip(regularity, 0, 1))
    except:
        return 0.5


def estimate_valence(spectral_centroids, spectral_rolloff) -> float:
    try:
        brightness = np.mean(spectral_centroids) / (np.mean(spectral_rolloff) + 1)
        return float(np.clip(brightness * 2, 0, 1))
    except:
        return 0.5


def estimate_acousticness(mfccs, spectral_centroids) -> float:
    try:
        timbre_complexity = np.std(mfccs)
        brightness = np.mean(spectral_centroids) / 1000.0
        acousticness = (timbre_complexity * 0.01) * (1.0 - brightness)
        return float(np.clip(acousticness, 0, 1))
    except:
        return 0.5


# ============================================================================
# RESUME LOGIC - Skip Already Analyzed Tracks
# ============================================================================

def get_existing_track_ids() -> set:
    """Get IDs of tracks already in the catalog."""
    try:
        from .database import DB_PATH
        import sqlite3
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT track_id FROM track_catalog")
        existing_ids = {row[0] for row in cursor.fetchall()}
        conn.close()
        
        print(f"[Resume] Found {len(existing_ids)} tracks already in catalog")
        return existing_ids
        
    except Exception as e:
        print(f"[Resume] Could not check existing tracks: {e}")
        return set()


def save_progress(current_index: int, total: int):
    """Save progress to file for resume capability."""
    try:
        with open(PROGRESS_FILE, 'w') as f:
            f.write(f"{current_index}/{total}\n")
    except:
        pass


def load_progress() -> int:
    """Load last saved progress."""
    try:
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, 'r') as f:
                line = f.read().strip()
                if '/' in line:
                    current, total = line.split('/')
                    return int(current)
    except:
        pass
    return 0


# ============================================================================
# MAIN BUILD FUNCTION
# ============================================================================

def build_catalog(username: str, target_size: int = 1000, resume: bool = True) -> int:
    """
    Build catalog using Spotify + Deezer hybrid approach - V2 IMPROVED!
    """
    try:
        from .spotify_client_v2 import get_spotify
        from .database import save_track_features
    except ImportError:
        print("ERROR: Could not import required modules.")
        return 0
    
    print(f"\n{'='*70}")
    print(f"  VIBELIST CATALOG BUILDER V2 - IMPROVED!")
    print(f"  Target: {target_size} total songs")
    print(f"  Resume mode: {'ON' if resume else 'OFF'}")
    print(f"{'='*70}\n")
    
    # Check existing catalog
    existing_ids = get_existing_track_ids() if resume else set()
    need_to_add = max(0, target_size - len(existing_ids))
    
    if len(existing_ids) >= target_size:
        print(f"✓ Catalog already has {len(existing_ids)} songs!")
        print(f"  (Target is {target_size})")
        return len(existing_ids)
    
    print(f"📊 Current catalog: {len(existing_ids)} songs")
    print(f"📊 Need to add: {need_to_add} more songs\n")
    
    # Connect to Spotify
    print("[1/5] Connecting to Spotify...")
    try:
        sp = get_spotify(username)
        print("✓ Connected\n")
    except Exception as e:
        print(f"ERROR: {e}")
        return 0
    
    # Fetch tracks from Spotify
    print(f"[2/5] Fetching {need_to_add * 2} candidates from Spotify...")
    spotify_tracks = get_popular_tracks_spotify(sp, limit=need_to_add * 2)
    
    # Filter out already-analyzed tracks
    new_tracks = [t for t in spotify_tracks if t["spotify_id"] not in existing_ids]
    
    print(f"✓ Found {len(new_tracks)} new tracks to analyze\n")
    
    if not new_tracks:
        print("No new tracks to add!")
        return len(existing_ids)
    
    # Analyze tracks
    print(f"[3/5] Matching to Deezer & downloading previews...")
    print(f"[4/5] Analyzing audio features...")
    print(f"[5/5] Storing in database...")
    print(f"(~8-12 seconds per song with retries)\n")
    
    analyzed_count = 0
    failed_count = 0
    start_index = load_progress()
    
    for i, track in enumerate(new_tracks, 1):
        if i <= start_index:
            continue  # Skip already processed
        
        track_name = track["name"]
        artist_name = track["artists"][0] if track["artists"] else ""
        
        # Progress indicator
        if i % 10 == 0:
            success_rate = (analyzed_count / i * 100) if i > 0 else 0
            print(f"\n📊 Progress: {i}/{len(new_tracks)} | ✓ {analyzed_count} | ✗ {failed_count} | Success: {success_rate:.1f}%")
            save_progress(i, len(new_tracks))
        
        safe_name = track_name[:35].ljust(35)
        safe_artist = artist_name[:18].ljust(18)
        print(f"[{i:4d}] {safe_name} - {safe_artist}...", end=" ", flush=True)
        
        # Find Deezer match (with fallbacks)
        preview_url = find_deezer_match_v2(track_name, artist_name)
        if not preview_url:
            print("❌ No match")
            failed_count += 1
            continue
        
        # Download preview
        audio_path = download_preview_deezer(preview_url, track["spotify_id"])
        if not audio_path:
            print("❌ Download failed")
            failed_count += 1
            continue
        
        # Analyze audio
        features = analyze_audio(audio_path)
        if not features:
            print("❌ Analysis failed")
            failed_count += 1
            continue
        
        # Store in database
        try:
            save_track_features(
                track_id=track["spotify_id"],
                track_uri=track["spotify_uri"],
                track_name=track["name"],
                artists=track["artists"],
                album=track["album"],
                popularity=track["popularity"],
                features=features
            )
            print("✓")
            analyzed_count += 1
        except Exception as e:
            print(f"❌ DB error")
            failed_count += 1
    
    # Clear progress file on completion
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
    
    total_in_catalog = len(existing_ids) + analyzed_count
    success_rate = (analyzed_count / len(new_tracks) * 100) if new_tracks else 0
    
    print(f"\n{'='*70}")
    print(f"  CATALOG BUILD COMPLETE!")
    print(f"  ✓ Successfully analyzed: {analyzed_count} songs")
    print(f"  ✗ Failed: {failed_count} songs")
    print(f"  📊 Success rate: {success_rate:.1f}%")
    print(f"  📊 Total catalog size: {total_in_catalog} songs")
    print(f"{'='*70}\n")
    
    return total_in_catalog


# ============================================================================
# COMMAND-LINE INTERFACE
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\n" + "="*70)
        print("  VibeList Catalog Builder V2 - IMPROVED")
        print("="*70)
        print("\nUsage:")
        print("  python -m backend.catalog_builder_v2 <username> [target_size] [--no-resume]")
        print("\nExamples:")
        print("  python -m backend.catalog_builder_v2 benijah 50        # Test with 50")
        print("  python -m backend.catalog_builder_v2 benijah 500       # Add 500 more")
        print("  python -m backend.catalog_builder_v2 benijah 1000      # Build to 1000")
        print("  python -m backend.catalog_builder_v2 benijah 1000 --no-resume  # Fresh start")
        print("\n" + "="*70 + "\n")
        sys.exit(1)
    
    username = sys.argv[1]
    target_size = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    resume = '--no-resume' not in sys.argv
    
    print(f"\nStarting catalog build for user: {username}")
    print(f"Target total size: {target_size} songs")
    print(f"Resume: {'Yes' if resume else 'No (fresh start)'}\n")
    
    count = build_catalog(username, target_size, resume)
    
    if count > 0:
        print(f"\n✨ Success! Your catalog now has {count} analyzed songs.")
        print(f"You can now generate even better vibe-based playlists! 🎵\n")
    else:
        print("\n❌ Catalog build failed. Check the errors above.\n")
