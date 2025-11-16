# backend/genre_blacklist.py
"""
Configurable genre blacklist - expand this as you discover problem genres
"""

# Hard blacklist: NEVER allow these genres
GENRE_BLACKLIST = {
    # Country variants
    "country", "contemporary-country", "country-road", "classic-country",
    "outlaw-country", "country-pop", "country-rock", "nashville",
    "bluegrass", "honky-tonk", "texas-country", "alt-country",
    
    # Add others as you find them bleeding in:
    # "folk-rock",  # if it's causing issues
}

# Soft blacklist: penalize but don't hard-reject (lower vibe score)
GENRE_PENALIZE = {
    "folk-rock",  # can be fine but sometimes too country-adjacent
    "americana",
}

# Genre synonyms for better matching
GENRE_SYNONYMS = {
    "lofi": "chillhop",
    "lo-fi": "chillhop", 
    "hiphop": "hip-hop",
    "hip hop": "hip-hop",
    "rnb": "r-n-b",
    "r&b": "r-n-b",
    "indiepop": "indie-pop",
    "indie pop": "indie-pop",
    "alt": "alternative",
    "altrock": "alt-rock",
    "alt rock": "alt-rock",
    "electro": "electronic",
    "edm": "electronic",  # edm is broader
    "death metal": "death-metal",
    "black metal": "black-metal",
    "heavy metal": "heavy-metal",
}

def normalize_genre(genre: str) -> str:
    """Apply synonyms to a genre string"""
    g = genre.lower().strip()
    return GENRE_SYNONYMS.get(g, g)

def is_blacklisted(artist_genres: set) -> bool:
    """Check if any artist genre is in blacklist"""
    return bool(GENRE_BLACKLIST & artist_genres)

def penalty_score(artist_genres: set) -> float:
    """Return penalty (0-1) for soft-blacklisted genres"""
    if GENRE_PENALIZE & artist_genres:
        return 0.2  # reduce vibe score by 0.2
    return 0.0