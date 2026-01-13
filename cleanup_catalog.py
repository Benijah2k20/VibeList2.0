# cleanup_catalog.py
"""
Clean up any corrupted rows in the catalog.
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("backend/vibelist.db")

def cleanup_catalog():
    """Fix or remove corrupted rows."""
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Find corrupted rows
    cursor.execute("SELECT track_id, track_name, artists FROM track_catalog")
    
    corrupted = []
    fixed = []
    
    for row in cursor.fetchall():
        track_id = row[0]
        track_name = row[1]
        artists_data = row[2]
        
        # Check if artists field is valid
        try:
            if artists_data:
                json.loads(artists_data)
                # Valid JSON
            else:
                # Empty field - mark as corrupted
                corrupted.append((track_id, track_name, "Empty artists field"))
        except json.JSONDecodeError:
            # Invalid JSON - try to fix
            if artists_data:
                # Try to fix: assume it's a plain string, convert to JSON array
                try:
                    fixed_artists = json.dumps([artists_data])
                    cursor.execute(
                        "UPDATE track_catalog SET artists = ? WHERE track_id = ?",
                        (fixed_artists, track_id)
                    )
                    fixed.append((track_id, track_name))
                except:
                    corrupted.append((track_id, track_name, "Invalid JSON"))
    
    conn.commit()
    
    print(f"\n{'='*80}")
    print("CATALOG CLEANUP REPORT")
    print(f"{'='*80}\n")
    print(f"Fixed: {len(fixed)} tracks")
    print(f"Corrupted (needs deletion): {len(corrupted)} tracks\n")
    
    if corrupted:
        print("Corrupted tracks:")
        for track_id, track_name, reason in corrupted[:10]:
            print(f"  - {track_name} ({reason})")
        
        if len(corrupted) > 10:
            print(f"  ... and {len(corrupted) - 10} more")
        
        print("\nDelete corrupted tracks? (y/n): ", end="")
        choice = input().strip().lower()
        
        if choice == 'y':
            for track_id, _, _ in corrupted:
                cursor.execute("DELETE FROM track_catalog WHERE track_id = ?", (track_id,))
            conn.commit()
            print(f"\n✓ Deleted {len(corrupted)} corrupted tracks")
    
    conn.close()
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    cleanup_catalog()