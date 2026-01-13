# backend/add_artists.py
"""
VibeList - Interactive Artist Downloader

Simple tool to add specific artists to your catalog.
Just type artist names and hit enter!

Usage:
    python3 add_artists.py
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

# Load environment variables from .env
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

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


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def search_artist(sp, artist_name: str) -> Optional[dict]:
    """
    Search for an artist by name and return their info.
    """
    try:
        results = sp.search(q=f"artist:{artist_name}", type='artist', limit=10)
        artists = results.get('artists', {}).get('items', [])
        
        if not artists:
            return None
        
        # Show options if multiple results
        if len(artists) > 1:
            print(f"\n📋 Found {len(artists)} artists matching '{artist_name}':")
            for i, artist in enumerate(artists[:5]):
                print(f"  {i+1}. {artist['name']} ({artist.get('genres', ['Unknown'])[:2]})")
            
            choice = input(f"\nSelect artist (1-{min(5, len(artists))}) or press Enter for #1: ").strip()
            
            if choice == "":
                idx = 0
            else:
                try:
                    idx = int(choice) - 1
                    if idx < 0 or idx >= len(artists):
                        idx = 0
                except:
                    idx = 0
            
            return artists[idx]
        
        return artists[0]
        
    except Exception as e:
        print(f"❌ Error searching for artist: {e}")
        return None


def get_artist_discography(sp, artist_id: str, artist_name: str) -> List[Dict]:
    """
    Get ALL tracks from an artist's discography.
    """
    print(f"\n🎵 Fetching discography for {artist_name}...")
    
    tracks = []
    seen_track_ids = set()
    
    try:
        # Get ALL albums
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
        
        print(f"   Found {len(albums)} albums/singles")
        
        # Get tracks from each album
        album_count = 0
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
                        'popularity': album.get('popularity', 0),
                    })
                
                album_count += 1
                if album_count % 10 == 0:
                    print(f"   Processed {album_count}/{len(albums)} albums...")
                
                time.sleep(0.1)
            except:
                continue
        
        print(f"   ✓ Got {len(tracks)} tracks from {artist_name}")
        return tracks
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return []


def find_deezer_match(track_name: str, artist_name: str, retries: int = 3) -> Optional[dict]:
    """
    Find matching track on Deezer with 3-stage fallback.
    
    Stage 1: Exact match (track + artist)
    Stage 2: Track name only
    Stage 3: Artist popular tracks
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
            
            # Stage 3: Artist name only (get popular tracks as fallback)
            try:
                artist_results = deezer_client.search_artists(artist_name)
                if artist_results and len(artist_results) > 0:
                    # Get the first matching artist
                    deezer_artist = artist_results[0]
                    # Get their top tracks
                    top_tracks = deezer_artist.get_top()
                    if top_tracks and len(top_tracks) > 0:
                        # Use first popular track from this artist
                        fallback_track = top_tracks[0]
                        return {
                            'id': fallback_track.id,
                            'preview': fallback_track.preview,
                            'duration': fallback_track.duration
                        }
            except:
                pass  # Stage 3 failed, will retry or return None
            
            time.sleep(0.2 * (attempt + 1))  # Exponential backoff
            
        except Exception as e:
            if attempt == retries - 1:
                # All stages failed after retries
                return None
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
    except:
        return False


def analyze_audio(file_path: Path) -> Optional[Dict]:
    """Analyze audio file using librosa."""
    try:
        y, sr = librosa.load(str(file_path), duration=30, sr=22050)
        
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
        rms = librosa.feature.rms(y=y)[0]
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        
        energy = float(np.mean(rms))
        tempo_val = float(tempo)
        
        features = {
            'tempo': tempo_val,
            'energy': min(1.0, energy * 2),
            'danceability': min(1.0, (energy + np.mean(zcr)) / 2),
            'valence': min(1.0, np.mean(spectral_centroids) / 4000),
            'acousticness': max(0.0, 1.0 - (np.mean(spectral_rolloff) / 8000)),
            'speechiness': min(1.0, np.mean(mfccs[0]) / 50),
            'instrumentalness': 0.5,
            'liveness': 0.1,
            'loudness': float(20 * np.log10(np.mean(rms) + 1e-10)),
            'key': 0,
            'mode': 1,
            'time_signature': 4,
        }
        
        return features
        
    except:
        return None


def process_track(track: Dict) -> Optional[Dict]:
    """Full pipeline: Find on Deezer → Download → Analyze → Return features."""
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
        if cache_file.exists():
            cache_file.unlink()
        return None
    
    # Combine track info + features
    result = {**track, **features, 'deezer_preview_url': preview_url}
    
    # Clean up cache
    if cache_file.exists():
        cache_file.unlink()
    
    return result


def save_to_database(tracks: List[Dict]):
    """Save analyzed tracks to database."""
    if not tracks:
        return
    
    print(f"\n💾 Saving {len(tracks)} tracks to database...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
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
        except:
            pass
    
    conn.commit()
    conn.close()
    
    print(f"   ✓ Saved {success_count}/{len(tracks)} tracks")


# ============================================================================
# MAIN INTERACTIVE FLOW
# ============================================================================

def main():
    """Main interactive flow."""
    print("\n" + "="*70)
    print("🎵  VIBELIST - INTERACTIVE ARTIST DOWNLOADER")
    print("="*70)
    print("\nAdd specific artists to your catalog by entering their names.")
    print("Hit Enter with no text to start downloading.\n")
    print("="*70 + "\n")
    
    # Check credentials
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ Error: Spotify credentials not found!")
        print("\nMake sure your .env file contains:")
        print("SPOTIFY_CLIENT_ID=your_id")
        print("SPOTIFY_CLIENT_SECRET=your_secret")
        return
    
    # Initialize Spotify
    auth_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    
    print("✓ Connected to Spotify\n")
    
    # Collect artist names
    artist_names = []
    
    print("Enter artist names (one per line):")
    print("Press Enter with no text when done.\n")
    
    while True:
        artist_name = input(f"Artist #{len(artist_names) + 1}: ").strip()
        
        if not artist_name:
            if len(artist_names) == 0:
                print("\n⚠️  No artists entered. Exiting.")
                return
            break
        
        artist_names.append(artist_name)
        print(f"   ✓ Added: {artist_name}")
    
    print(f"\n{'='*70}")
    print(f"📋 Summary: {len(artist_names)} artist(s) to download")
    for i, name in enumerate(artist_names, 1):
        print(f"  {i}. {name}")
    print(f"{'='*70}\n")
    
    confirm = input("Continue? (Y/n): ").strip().lower()
    if confirm == 'n':
        print("\n❌ Cancelled.")
        return
    
    # Process each artist
    all_tracks_analyzed = []
    
    for i, artist_name in enumerate(artist_names, 1):
        print(f"\n{'='*70}")
        print(f"Artist {i}/{len(artist_names)}: {artist_name}")
        print(f"{'='*70}")
        
        # Search for artist
        artist = search_artist(sp, artist_name)
        if not artist:
            print(f"❌ Could not find artist: {artist_name}")
            continue
        
        artist_id = artist['id']
        artist_name_confirmed = artist['name']
        
        print(f"✓ Found: {artist_name_confirmed}")
        print(f"  Genres: {', '.join(artist.get('genres', ['Unknown'])[:3])}")
        print(f"  Popularity: {artist.get('popularity', 0)}/100")
        
        # Get discography
        tracks = get_artist_discography(sp, artist_id, artist_name_confirmed)
        
        if not tracks:
            print(f"❌ No tracks found for {artist_name_confirmed}")
            continue
        
        # Analyze tracks
        print(f"\n🔍 Analyzing {len(tracks)} tracks...")
        print("This may take a while...\n")
        
        analyzed = []
        failed = 0
        
        for j, track in enumerate(tracks, 1):
            # Progress indicator
            if j % 10 == 0 or j == 1:
                print(f"  [{j}/{len(tracks)}] {track['name'][:50]}")
            
            result = process_track(track)
            
            if result:
                analyzed.append(result)
            else:
                failed += 1
            
            # Save periodically
            if len(analyzed) % 50 == 0 and len(analyzed) > 0:
                save_to_database(analyzed)
                all_tracks_analyzed.extend(analyzed)
                analyzed = []
            
            time.sleep(0.2)  # Rate limiting
        
        # Save remaining
        if analyzed:
            save_to_database(analyzed)
            all_tracks_analyzed.extend(analyzed)
        
        # Artist summary
        success_count = len(tracks) - failed
        success_rate = (success_count / len(tracks)) * 100 if tracks else 0
        
        print(f"\n✓ Completed: {artist_name_confirmed}")
        print(f"  Total tracks: {len(tracks)}")
        print(f"  Analyzed: {success_count}")
        print(f"  Failed: {failed}")
        print(f"  Success rate: {success_rate:.1f}%")
    
    # Final summary
    print(f"\n{'='*70}")
    print("🎉 ALL ARTISTS COMPLETE!")
    print(f"{'='*70}")
    print(f"Total tracks analyzed: {len(all_tracks_analyzed)}")
    print(f"Artists processed: {len(artist_names)}")
    print(f"{'='*70}\n")
    
    # Show updated catalog size
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM track_catalog")
    total = cursor.fetchone()[0]
    conn.close()
    
    print(f"📊 Your catalog now has {total:,} tracks!\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Progress has been saved.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
