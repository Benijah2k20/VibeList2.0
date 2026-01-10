# backend/catalog_artist_deep_dive.py
"""
Download an entire artist's discography for VibeList catalog.
"""
import sys
import time
from .catalog_builder_v2 import (
    find_deezer_match_v2,
    download_preview_deezer,
    analyze_audio,
    get_existing_track_ids
)

def get_artist_full_catalog(sp, artist_name: str, max_tracks: int = 200):
    """Get all tracks from an artist (albums + singles + features)."""
    print(f"\n[Artist] Searching for: {artist_name}")
    
    # Search for the artist
    results = sp.search(q=f'artist:"{artist_name}"', type='artist', limit=1)
    
    if not results['artists']['items']:
        print(f"[Artist] Not found: {artist_name}")
        return []
    
    artist = results['artists']['items'][0]
    artist_id = artist['id']
    artist_name_verified = artist['name']
    
    print(f"[Artist] Found: {artist_name_verified} (ID: {artist_id})")
    print(f"[Artist] Popularity: {artist['popularity']}")
    
    tracks = []
    seen_ids = set()
    
    # Get all albums
    print(f"[Artist] Fetching albums...")
    albums = []
    offset = 0
    while True:
        results = sp.artist_albums(artist_id, album_type='album,single', limit=50, offset=offset)
        albums.extend(results['items'])
        if not results['next']:
            break
        offset += 50
        time.sleep(0.3)
    
    print(f"[Artist] Found {len(albums)} albums/singles")
    
    # Get tracks from each album
    print(f"[Artist] Fetching tracks from albums...")
    for album in albums:
        if len(tracks) >= max_tracks:
            break
        
        album_tracks = sp.album_tracks(album['id'])['items']
        
        for track in album_tracks:
            if len(tracks) >= max_tracks:
                break
            
            if track['id'] in seen_ids:
                continue
            
            seen_ids.add(track['id'])
            
            # Get full track details
            full_track = sp.track(track['id'])
            
            tracks.append({
                "spotify_id": full_track["id"],
                "spotify_uri": full_track["uri"],
                "name": full_track["name"],
                "artists": [a["name"] for a in full_track.get("artists", [])],
                "album": full_track.get("album", {}).get("name", ""),
                "popularity": full_track.get("popularity", 0),
            })
        
        time.sleep(0.3)
    
    print(f"[Artist] ✓ Collected {len(tracks)} unique tracks")
    return tracks


def download_artist_catalog(username: str, artist_name: str, max_tracks: int = 200):
    """Download and analyze an artist's full catalog."""
    try:
        from .spotify_client_v2 import get_spotify
        from .database import save_track_features
    except ImportError:
        from spotify_client_v2 import get_spotify
        from database import save_track_features
    
    print(f"\n{'='*70}")
    print(f"  ARTIST DEEP DIVE: {artist_name}")
    print(f"  Max tracks: {max_tracks}")
    print(f"{'='*70}\n")
    
    # Check existing
    existing_ids = get_existing_track_ids()
    
    # Connect to Spotify
    print("[1/3] Connecting to Spotify...")
    sp = get_spotify(username)
    print("✓ Connected\n")
    
    # Get artist's catalog
    print(f"[2/3] Fetching {artist_name}'s discography...")
    tracks = get_artist_full_catalog(sp, artist_name, max_tracks)
    
    # Filter out existing
    new_tracks = [t for t in tracks if t["spotify_id"] not in existing_ids]
    already_have = len(tracks) - len(new_tracks)
    
    print(f"\n✓ Found {len(tracks)} total tracks")
    print(f"  Already in catalog: {already_have}")
    print(f"  New to analyze: {len(new_tracks)}\n")
    
    if not new_tracks:
        print("All tracks already in catalog!")
        return
    
    # Analyze
    print(f"[3/3] Analyzing {len(new_tracks)} tracks...")
    
    analyzed = 0
    failed = 0
    
    for i, track in enumerate(new_tracks, 1):
        track_name = track["name"]
        artist_name_track = track["artists"][0] if track["artists"] else artist_name
        
        if i % 10 == 0:
            print(f"\n📊 Progress: {i}/{len(new_tracks)} | ✓ {analyzed} | ✗ {failed}")
        
        print(f"[{i:4d}] {track_name[:50]:<50}...", end=" ", flush=True)
        
        # Find on Deezer
        preview_url = find_deezer_match_v2(track_name, artist_name_track)
        if not preview_url:
            print("❌ No match")
            failed += 1
            continue
        
        # Download
        audio_path = download_preview_deezer(preview_url, track["spotify_id"])
        if not audio_path:
            print("❌ Download failed")
            failed += 1
            continue
        
        # Analyze
        features = analyze_audio(audio_path)
        if not features:
            print("❌ Analysis failed")
            failed += 1
            continue
        
        # Save
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
            analyzed += 1
        except Exception as e:
            print(f"❌ DB error")
            failed += 1
    
    success_rate = (analyzed / len(new_tracks) * 100) if new_tracks else 0
    
    print(f"\n{'='*70}")
    print(f"  ARTIST DEEP DIVE COMPLETE!")
    print(f"  ✓ Successfully analyzed: {analyzed} tracks")
    print(f"  ✗ Failed: {failed} tracks")
    print(f"  📊 Success rate: {success_rate:.1f}%")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nUsage:")
        print('  python -m backend.catalog_artist_deep_dive <username> "<artist name>" [max_tracks]')
        print("\nExamples:")
        print('  python -m backend.catalog_artist_deep_dive benijah "Kendrick Lamar"')
        print('  python -m backend.catalog_artist_deep_dive benijah "The Weeknd" 100')
        print()
        sys.exit(1)
    
    username = sys.argv[1]
    artist_name = sys.argv[2]
    max_tracks = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    
    download_artist_catalog(username, artist_name, max_tracks)