# show_catalog.py
"""
VibeList Catalog Explorer - Interactive catalog browser with search and sort.

Usage:
    python show_catalog.py
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("backend/vibelist.db")


def safe_parse_artists(artists_data):
    """Safely parse artists field with error handling."""
    try:
        if not artists_data:
            return "Unknown"
        
        if isinstance(artists_data, str):
            # Try to parse as JSON
            try:
                artists = json.loads(artists_data)
                if isinstance(artists, list):
                    return ", ".join(artists)
                return str(artists)
            except json.JSONDecodeError:
                # Not JSON, treat as plain string
                return artists_data
        
        return str(artists_data)
    except:
        return "Unknown"


def get_catalog_stats():
    """Get overall catalog statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Total tracks
    cursor.execute("SELECT COUNT(*) FROM track_catalog")
    total = cursor.fetchone()[0]
    
    # Unique artists
    cursor.execute("SELECT DISTINCT artists FROM track_catalog")
    unique_artists = len(set([safe_parse_artists(row[0]) for row in cursor.fetchall()]))
    
    # Average stats
    cursor.execute("""
        SELECT 
            AVG(popularity) as avg_pop,
            AVG(energy) as avg_energy,
            AVG(valence) as avg_valence,
            AVG(tempo) as avg_tempo,
            MIN(tempo) as min_tempo,
            MAX(tempo) as max_tempo
        FROM track_catalog
    """)
    stats = cursor.fetchone()
    
    conn.close()
    
    return {
        'total': total,
        'unique_artists': unique_artists,
        'avg_popularity': stats[0],
        'avg_energy': stats[1],
        'avg_valence': stats[2],
        'avg_tempo': stats[3],
        'min_tempo': stats[4],
        'max_tempo': stats[5]
    }


def show_overview():
    """Show catalog overview."""
    stats = get_catalog_stats()
    
    print("\n" + "="*80)
    print(f"  VIBELIST CATALOG - {stats['total']:,} SONGS")
    print("="*80)
    print(f"\n  📊 Overview:")
    print(f"     Total Tracks:      {stats['total']:,}")
    print(f"     Unique Artists:    {stats['unique_artists']:,}")
    print(f"\n  📈 Averages:")
    print(f"     Popularity:        {stats['avg_popularity']:.1f}/100")
    print(f"     Energy:            {stats['avg_energy']:.2f}")
    print(f"     Valence:           {stats['avg_valence']:.2f}")
    print(f"     Tempo:             {stats['avg_tempo']:.0f} BPM (range: {stats['min_tempo']:.0f}-{stats['max_tempo']:.0f})")
    print("="*80 + "\n")


def display_tracks(tracks, title="Tracks"):
    """Display a list of tracks in formatted table with pagination."""
    if not tracks:
        print("\n❌ No tracks found.\n")
        return
    
    total_tracks = len(tracks)
    print(f"\n{title} ({total_tracks} results):\n")
    
    # If more than 50 tracks, ask if user wants to see all or paginate
    if total_tracks > 50:
        print(f"⚠️  Found {total_tracks} tracks. That's a lot!")
        choice = input("Show (a)ll, first (50), or (c)ancel? [a/50/c]: ").strip().lower()
        
        if choice == 'c':
            print("\n❌ Cancelled.\n")
            return
        elif choice == '50':
            tracks = tracks[:50]
            print(f"\nShowing first 50 of {total_tracks} results:\n")
        else:
            print(f"\nShowing all {total_tracks} results:\n")
    
    print(f"{'#':<4} {'Track':<35} {'Artist':<25} {'Pop':>4} {'Energy':>6} {'Val':>5} {'Tempo':>5}")
    print("-" * 90)
    
    for i, track in enumerate(tracks, 1):
        track_name = track['name'][:34] if track['name'] else "Unknown"
        artist_str = safe_parse_artists(track['artists'])[:24]
        
        print(f"{i:<4} {track_name:<35} {artist_str:<25} "
              f"{track['popularity']:>4} {track['energy']:>6.2f} "
              f"{track['valence']:>5.2f} {track['tempo']:>5.0f}")
        
        # Pause every 50 tracks for readability
        if i % 50 == 0 and i < len(tracks):
            input(f"\nShowing {i}/{len(tracks)}... Press Enter to continue...")
            print()
    
    print()


def search_by_artist(artist_query, limit=None):
    """Search tracks by artist name."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if limit:
        cursor.execute("""
            SELECT track_name, artists, popularity, energy, valence, tempo
            FROM track_catalog
            WHERE artists LIKE ?
            ORDER BY popularity DESC
            LIMIT ?
        """, (f"%{artist_query}%", limit))
    else:
        cursor.execute("""
            SELECT track_name, artists, popularity, energy, valence, tempo
            FROM track_catalog
            WHERE artists LIKE ?
            ORDER BY popularity DESC
        """, (f"%{artist_query}%",))
    
    tracks = []
    for row in cursor.fetchall():
        tracks.append({
            'name': row[0],
            'artists': row[1],
            'popularity': row[2] or 0,
            'energy': row[3] or 0,
            'valence': row[4] or 0,
            'tempo': row[5] or 0
        })
    
    conn.close()
    return tracks


def search_by_song(song_query, limit=None):
    """Search tracks by song name."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if limit:
        cursor.execute("""
            SELECT track_name, artists, popularity, energy, valence, tempo
            FROM track_catalog
            WHERE track_name LIKE ?
            ORDER BY popularity DESC
            LIMIT ?
        """, (f"%{song_query}%", limit))
    else:
        cursor.execute("""
            SELECT track_name, artists, popularity, energy, valence, tempo
            FROM track_catalog
            WHERE track_name LIKE ?
            ORDER BY popularity DESC
        """, (f"%{song_query}%",))
    
    tracks = []
    for row in cursor.fetchall():
        tracks.append({
            'name': row[0],
            'artists': row[1],
            'popularity': row[2] or 0,
            'energy': row[3] or 0,
            'valence': row[4] or 0,
            'tempo': row[5] or 0
        })
    
    conn.close()
    return tracks


def search_by_vibe(energy_range=None, valence_range=None, tempo_range=None, limit=100):
    """Search tracks by vibe parameters."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = "SELECT track_name, artists, popularity, energy, valence, tempo FROM track_catalog WHERE 1=1"
    params = []
    
    if energy_range:
        query += " AND energy BETWEEN ? AND ?"
        params.extend(energy_range)
    
    if valence_range:
        query += " AND valence BETWEEN ? AND ?"
        params.extend(valence_range)
    
    if tempo_range:
        query += " AND tempo BETWEEN ? AND ?"
        params.extend(tempo_range)
    
    query += " ORDER BY popularity DESC"
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    
    cursor.execute(query, params)
    
    tracks = []
    for row in cursor.fetchall():
        tracks.append({
            'name': row[0],
            'artists': row[1],
            'popularity': row[2] or 0,
            'energy': row[3] or 0,
            'valence': row[4] or 0,
            'tempo': row[5] or 0
        })
    
    conn.close()
    return tracks


def show_top_tracks(sort_by='popularity', limit=20):
    """Show top tracks sorted by specified criteria."""
    valid_sorts = ['popularity', 'energy', 'valence', 'tempo']
    if sort_by not in valid_sorts:
        sort_by = 'popularity'
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(f"""
        SELECT track_name, artists, popularity, energy, valence, tempo
        FROM track_catalog
        ORDER BY {sort_by} DESC
        LIMIT ?
    """, (limit,))
    
    tracks = []
    for row in cursor.fetchall():
        tracks.append({
            'name': row[0],
            'artists': row[1],
            'popularity': row[2] or 0,
            'energy': row[3] or 0,
            'valence': row[4] or 0,
            'tempo': row[5] or 0
        })
    
    conn.close()
    return tracks


def show_artist_stats(limit=20):
    """Show statistics by artist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT artists, COUNT(*) as track_count,
               AVG(popularity) as avg_pop,
               AVG(energy) as avg_energy,
               AVG(valence) as avg_valence
        FROM track_catalog
        GROUP BY artists
        ORDER BY track_count DESC
        LIMIT ?
    """, (limit,))
    
    print(f"\nTop {limit} Artists by Track Count:\n")
    print(f"{'Artist':<30} {'Tracks':>7} {'Avg Pop':>8} {'Avg Energy':>11} {'Avg Valence':>12}")
    print("-" * 80)
    
    for row in cursor.fetchall():
        artist = safe_parse_artists(row[0])[:29]
        track_count = row[1]
        avg_pop = row[2] or 0
        avg_energy = row[3] or 0
        avg_valence = row[4] or 0
        
        print(f"{artist:<30} {track_count:>7} {avg_pop:>8.1f} {avg_energy:>11.2f} {avg_valence:>12.2f}")
    
    print()
    conn.close()


def show_menu():
    """Display main menu."""
    print("\n" + "="*80)
    print("  VIBELIST CATALOG EXPLORER")
    print("="*80)
    print("\n  1. Show Overview")
    print("  2. Search by Artist")
    print("  3. Search by Song Name")
    print("  4. Search by Vibe (Energy/Valence/Tempo)")
    print("  5. Show Top Tracks by Popularity")
    print("  6. Show Top Tracks by Energy")
    print("  7. Show Top Tracks by Valence")
    print("  8. Show Top Tracks by Tempo")
    print("  9. Show Artist Statistics")
    print("  0. Exit")
    print("\n" + "="*80)


def get_float_input(prompt, default=None):
    """Get float input with default value."""
    try:
        value = input(prompt).strip()
        if not value and default is not None:
            return default
        return float(value)
    except:
        return default


def interactive_mode():
    """Run interactive catalog explorer."""
    show_overview()
    
    while True:
        show_menu()
        choice = input("\nSelect option (0-9): ").strip()
        
        if choice == '0':
            print("\n👋 Goodbye!\n")
            break
        
        elif choice == '1':
            show_overview()
        
        elif choice == '2':
            artist = input("\nEnter artist name: ").strip()
            if artist:
                tracks = search_by_artist(artist)  # No limit - get all tracks
                display_tracks(tracks, f"Tracks by '{artist}'")
        
        elif choice == '3':
            song = input("\nEnter song name: ").strip()
            if song:
                tracks = search_by_song(song)  # No limit - get all tracks
                display_tracks(tracks, f"Songs matching '{song}'")
        
        elif choice == '4':
            print("\nSearch by Vibe (press Enter to skip any parameter)")
            
            energy_min = get_float_input("  Energy min (0.0-1.0): ")
            energy_max = get_float_input("  Energy max (0.0-1.0): ")
            
            valence_min = get_float_input("  Valence min (0.0-1.0): ")
            valence_max = get_float_input("  Valence max (0.0-1.0): ")
            
            tempo_min = get_float_input("  Tempo min (BPM): ")
            tempo_max = get_float_input("  Tempo max (BPM): ")
            
            energy_range = [energy_min, energy_max] if energy_min is not None and energy_max is not None else None
            valence_range = [valence_min, valence_max] if valence_min is not None and valence_max is not None else None
            tempo_range = [tempo_min, tempo_max] if tempo_min is not None and tempo_max is not None else None
            
            tracks = search_by_vibe(energy_range, valence_range, tempo_range)
            display_tracks(tracks, "Tracks matching vibe")
        
        elif choice == '5':
            tracks = show_top_tracks('popularity')
            display_tracks(tracks, "Top 20 by Popularity")
        
        elif choice == '6':
            tracks = show_top_tracks('energy')
            display_tracks(tracks, "Top 20 by Energy")
        
        elif choice == '7':
            tracks = show_top_tracks('valence')
            display_tracks(tracks, "Top 20 by Valence (Happiness)")
        
        elif choice == '8':
            tracks = show_top_tracks('tempo')
            display_tracks(tracks, "Top 20 by Tempo")
        
        elif choice == '9':
            show_artist_stats()
        
        else:
            print("\n❌ Invalid option. Please try again.")
        
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        interactive_mode()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!\n")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
