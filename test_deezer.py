import deezer

# No authentication needed!
client = deezer.Client()

# Search for a track
results = client.search('Drake God\'s Plan')

if results:
    track = results[0]
    print("="*60)
    print(f"Track: {track.title}")
    print(f"Artist: {track.artist.name}")
    print(f"Preview URL: {track.preview}")
    print(f"Duration: {track.duration}s")
    print("="*60)
    
    if track.preview:
        print("\n✅ PREVIEW URL EXISTS!")
        print(f"URL: {track.preview}")
    else:
        print("\n❌ No preview URL")
else:
    print("No results found")