"use client";

import { useEffect, useState, useMemo } from "react";
import Image from "next/image";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

// Debounce helper
function debounce(fn, ms = 300) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export default function Home() {
  // Basic state
  const [username, setUsername] = useState("benijah");
  const [connected, setConnected] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Steering controls
  const [allGenres, setAllGenres] = useState([]);
  const [selectedGenres, setSelectedGenres] = useState([]);
  const [selectedArtistIds, setSelectedArtistIds] = useState([]);
  const [selectedArtistNames, setSelectedArtistNames] = useState([]);
  const [artistQuery, setArtistQuery] = useState("");
  const [artistResults, setArtistResults] = useState([]);
  const [energy, setEnergy] = useState(0.5);

  // Preview state
  const [previewTracks, setPreviewTracks] = useState(null);
  const [vibeParams, setVibeParams] = useState(null);
  const [votes, setVotes] = useState({}); // {track_id: 'up'|'down'}
  const [replacing, setReplacing] = useState({}); // {track_id: boolean}

  // Check Spotify connection on mount
  useEffect(() => {
    checkSpotifyStatus();
  }, [username]);

  async function checkSpotifyStatus() {
    try {
      const res = await fetch(
        `${API_BASE}/spotify/status?username=${encodeURIComponent(username)}`
      );
      const data = await res.json();
      setConnected(data.connected);
    } catch (err) {
      console.error("Failed to check Spotify status:", err);
    }
  }

  // Load available genres
  useEffect(() => {
    if (!connected) return;
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/spotify/genres?username=${encodeURIComponent(username)}`
        );
        if (!res.ok) return;
        const data = await res.json();
        setAllGenres((data.genres || []).sort());
      } catch (err) {
        console.error("Failed to load genres:", err);
      }
    })();
  }, [connected, username]);

  // Connect to Spotify
  async function connectSpotify() {
    try {
      const res = await fetch(
        `${API_BASE}/spotify/login?username=${encodeURIComponent(username)}`
      );
      const { auth_url } = await res.json();
      window.location.href = auth_url;
    } catch (err) {
      alert("Error connecting to Spotify");
      console.error(err);
    }
  }

  // Search artists (debounced)
  const debouncedSearchArtists = useMemo(
    () =>
      debounce(async (q) => {
        if (!q || q.trim().length < 2) {
          setArtistResults([]);
          return;
        }
        try {
          const res = await fetch(
            `${API_BASE}/spotify/search/artists?username=${encodeURIComponent(
              username
            )}&query=${encodeURIComponent(q)}`
          );
          if (!res.ok) return;
          const data = await res.json();
          setArtistResults(data.artists || []);
        } catch (err) {
          setArtistResults([]);
        }
      }, 300),
    [username]
  );

  function addArtist(artist) {
    if (!selectedArtistIds.includes(artist.id)) {
      setSelectedArtistIds((prev) => [...prev, artist.id]);
      setSelectedArtistNames((prev) => [...prev, artist.name]);
    }
    setArtistQuery("");
    setArtistResults([]);
  }

  function removeArtist(id) {
    const idx = selectedArtistIds.indexOf(id);
    if (idx === -1) return;
    setSelectedArtistIds((prev) => prev.filter((_, i) => i !== idx));
    setSelectedArtistNames((prev) => prev.filter((_, i) => i !== idx));
  }

  // Generate preview
  async function handleGeneratePreview(e) {
    e.preventDefault();
    setError("");
    setPreviewTracks(null);
    setVotes({});

    if (!prompt.trim()) {
      setError("Please enter a vibe description");
      return;
    }

    setLoading(true);
    try {
      const params = new URLSearchParams({
        username,
        prompt,
        limit: "15",
      });

      if (selectedArtistIds.length > 0) {
        params.set("artists", selectedArtistIds.join(","));
      }
      if (selectedGenres.length > 0) {
        params.set("genres", selectedGenres.join(","));
      }
      if (energy !== 0.5) {
        params.set("energy", String(energy));
      }

      const res = await fetch(
        `${API_BASE}/playlist/generate?${params.toString()}`,
        { method: "POST" }
      );

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || `Error: ${res.status}`);
      }

      const data = await res.json();
      setPreviewTracks(data.tracks);
      setVibeParams(data.vibe_params);
    } catch (err) {
      setError(err.message || "Failed to generate preview");
    } finally {
      setLoading(false);
    }
  }

  // Handle thumbs up/down
  function handleVote(trackId, vote) {
    setVotes((prev) => ({ ...prev, [trackId]: vote }));
  }

  // Replace track (thumbs down)
  async function handleReplace(trackId) {
    setReplacing((prev) => ({ ...prev, [trackId]: true }));

    try {
      // Get all current track URIs except the one being replaced
      const excludeUris = previewTracks
        .filter((t) => t.id !== trackId)
        .map((t) => t.uri)
        .join(",");

      const params = new URLSearchParams({
        username,
        prompt,
        exclude_uris: excludeUris,
      });

      if (selectedArtistIds.length > 0) {
        params.set("artists", selectedArtistIds.join(","));
      }
      if (selectedGenres.length > 0) {
        params.set("genres", selectedGenres.join(","));
      }
      if (energy !== 0.5) {
        params.set("energy", String(energy));
      }

      const res = await fetch(
        `${API_BASE}/playlist/replace?${params.toString()}`,
        { method: "POST" }
      );

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Failed to find replacement");
      }

      const data = await res.json();

      // Replace the track
      setPreviewTracks((prev) =>
        prev.map((t) => (t.id === trackId ? data.track : t))
      );

      // Clear vote for replaced track
      setVotes((prev) => {
        const newVotes = { ...prev };
        delete newVotes[trackId];
        return newVotes;
      });
    } catch (err) {
      alert(err.message || "Failed to replace track");
    } finally {
      setReplacing((prev) => ({ ...prev, [trackId]: false }));
    }
  }

  // Create final playlist
  async function handleCreatePlaylist() {
    if (!previewTracks || previewTracks.length === 0) {
      alert("No tracks to create playlist with");
      return;
    }

    // Check if all tracks are approved
    const allApproved = previewTracks.every((t) => votes[t.id] === "up");
    if (!allApproved) {
      alert("Please approve all tracks (thumbs up) before creating playlist");
      return;
    }

    setLoading(true);
    try {
      const trackUris = previewTracks.map((t) => t.uri).join(",");

      const params = new URLSearchParams({
        username,
        prompt,
        track_uris: trackUris,
        public: "false",
      });

      const res = await fetch(
        `${API_BASE}/playlist/create?${params.toString()}`,
        { method: "POST" }
      );

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Failed to create playlist");
      }

      const data = await res.json();

      // Open playlist in new tab
      if (data.playlist_url) {
        window.open(data.playlist_url, "_blank");
        alert(
          `✓ Playlist created with ${data.track_count} tracks! Opening Spotify...`
        );
        // Reset preview
        setPreviewTracks(null);
        setVotes({});
      }
    } catch (err) {
      alert(err.message || "Failed to create playlist");
    } finally {
      setLoading(false);
    }
  }

  // UI helpers
  const allApproved =
    previewTracks &&
    previewTracks.every((t) => votes[t.id] === "up") &&
    Object.keys(votes).length === previewTracks.length;

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-4xl font-bold mb-2 text-white">VibeList</h1>
        <p className="text-gray-300 mb-8">AI-powered playlist generator</p>

        {/* Connection status */}
        <div className="mb-8 p-4 rounded-lg bg-gray-800 border border-gray-700">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-medium text-white">Spotify: </span>
              <span
                className={
                  connected ? "text-green-400 font-semibold" : "text-yellow-400 font-semibold"
                }
              >
                {connected ? "✓ Connected" : "⚠ Not Connected"}
              </span>
            </div>
            {!connected && (
              <button
                onClick={connectSpotify}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 font-semibold"
              >
                Connect Spotify
              </button>
            )}
          </div>
        </div>

        {/* Main form */}
        {connected && (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-6 mb-8">
            <form onSubmit={handleGeneratePreview}>
              {/* Prompt */}
              <div className="mb-6">
                <label className="block font-medium mb-2 text-white text-lg">
                  Describe your vibe
                </label>
                <input
                  type="text"
                  className="w-full bg-gray-900 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  placeholder="e.g., hip hop party, rainy night drive, workout energy..."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              </div>

              {/* Genres */}
              <div className="mb-6">
                <label className="block font-medium mb-2 text-white text-lg">
                  Select genres (optional)
                </label>
                <div className="flex flex-wrap gap-2">
                  {allGenres.slice(0, 20).map((genre) => (
                    <button
                      key={genre}
                      type="button"
                      onClick={() =>
                        setSelectedGenres((prev) =>
                          prev.includes(genre)
                            ? prev.filter((g) => g !== genre)
                            : [...prev, genre]
                        )
                      }
                      className={`px-4 py-2 rounded-full text-sm font-semibold transition ${
                        selectedGenres.includes(genre)
                          ? "bg-blue-600 text-white shadow-lg"
                          : "bg-gray-700 text-gray-200 hover:bg-gray-600 border border-gray-600"
                      }`}
                    >
                      {genre}
                    </button>
                  ))}
                </div>
                {selectedGenres.length > 0 && (
                  <div className="mt-2 text-sm text-blue-300 font-medium">
                    Selected: {selectedGenres.join(", ")}
                  </div>
                )}
              </div>

              {/* Artists */}
              <div className="mb-6">
                <label className="block font-medium mb-2 text-white text-lg">
                  Prefer specific artists (optional)
                </label>
                <input
                  type="text"
                  className="w-full bg-gray-900 border border-gray-600 rounded-lg px-4 py-2 mb-2 text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  placeholder="Search for artists..."
                  value={artistQuery}
                  onChange={(e) => {
                    setArtistQuery(e.target.value);
                    debouncedSearchArtists(e.target.value);
                  }}
                />

                {/* Search results */}
                {artistResults.length > 0 && (
                  <div className="border border-gray-600 rounded-lg mb-2 max-h-48 overflow-auto bg-gray-900">
                    {artistResults.map((artist) => (
                      <button
                        key={artist.id}
                        type="button"
                        onClick={() => addArtist(artist)}
                        className="w-full px-4 py-2 hover:bg-gray-700 text-left flex items-center gap-3 text-white border-b border-gray-700 last:border-b-0"
                      >
                        {artist.image && (
                          <div className="relative w-10 h-10 rounded-full overflow-hidden bg-gray-700">
                            <Image
                              src={artist.image}
                              alt={artist.name}
                              fill
                              className="object-cover"
                            />
                          </div>
                        )}
                        <span className="font-medium">{artist.name}</span>
                      </button>
                    ))}
                  </div>
                )}

                {/* Selected artists */}
                {selectedArtistNames.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {selectedArtistNames.map((name, idx) => (
                      <span
                        key={selectedArtistIds[idx]}
                        className="inline-flex items-center gap-2 px-3 py-1.5 bg-green-600 rounded-full text-sm font-semibold text-white"
                      >
                        {name}
                        <button
                          type="button"
                          onClick={() =>
                            removeArtist(selectedArtistIds[idx])
                          }
                          className="text-white hover:text-gray-200 font-bold"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Energy slider */}
              <div className="mb-6">
                <label className="block font-medium mb-2 flex justify-between text-white">
                  <span className="text-lg">Energy Level</span>
                  <span className="text-blue-400 font-bold">{energy.toFixed(2)}</span>
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={energy}
                  onChange={(e) => setEnergy(parseFloat(e.target.value))}
                  className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
                <div className="flex justify-between text-sm text-gray-300 mt-1 font-medium">
                  <span>Chill</span>
                  <span>Intense</span>
                </div>
              </div>

              {/* Submit button */}
              <button
                type="submit"
                disabled={loading || !prompt.trim()}
                className="w-full py-4 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg font-bold text-lg hover:from-blue-700 hover:to-blue-800 disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed shadow-lg transition"
              >
                {loading ? "Generating..." : "Generate Preview"}
              </button>
            </form>
          </div>
        )}

        {/* Error display */}
        {error && (
          <div className="bg-red-900 border border-red-600 text-red-200 px-4 py-3 rounded-lg mb-8 font-medium">
            {error}
          </div>
        )}

        {/* Preview section */}
        {previewTracks && (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-bold text-white">Preview Playlist</h2>
                <p className="text-gray-300 mt-1 font-medium">
                  {previewTracks.length} tracks • Vote on each track
                </p>
              </div>
              <button
                onClick={handleCreatePlaylist}
                disabled={!allApproved || loading}
                className={`px-6 py-3 rounded-lg font-bold text-lg shadow-lg ${
                  allApproved && !loading
                    ? "bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 text-white"
                    : "bg-gray-700 text-gray-500 cursor-not-allowed"
                }`}
              >
                {loading
                  ? "Creating..."
                  : allApproved
                  ? "Create Playlist ✓"
                  : "Vote on all tracks first"}
              </button>
            </div>

            {/* Track grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {previewTracks.map((track) => (
                <TrackCard
                  key={track.id}
                  track={track}
                  vote={votes[track.id]}
                  isReplacing={replacing[track.id]}
                  onVote={(vote) => handleVote(track.id, vote)}
                  onReplace={() => handleReplace(track.id)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

// Track card component
function TrackCard({ track, vote, isReplacing, onVote, onReplace }) {
  const formatDuration = (ms) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className={`border-2 rounded-lg overflow-hidden transition-all shadow-lg ${
        vote === "up"
          ? "ring-4 ring-green-500 border-green-500"
          : vote === "down"
          ? "ring-4 ring-red-500 border-red-500"
          : "border-gray-600"
      } ${isReplacing ? "opacity-50" : ""} bg-gray-900`}
    >
      {/* Album art */}
      <div className="relative w-full h-48 bg-gray-800">
        {track.album.image ? (
          <Image
            src={track.album.image}
            alt={track.album.name}
            fill
            className="object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-500 font-medium">
            No Image
          </div>
        )}
        {isReplacing && (
          <div className="absolute inset-0 bg-black/70 flex items-center justify-center text-white font-bold">
            Finding replacement...
          </div>
        )}
      </div>

      {/* Track info */}
      <div className="p-4 bg-gray-900">
        <h3 className="font-bold mb-1 truncate text-white" title={track.name}>
          {track.name}
        </h3>
        <p className="text-sm text-gray-300 truncate font-medium">
          {track.artists.map((a) => a.name).join(", ")}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          {track.album.name} • {formatDuration(track.duration_ms)}
        </p>

        {/* Vote buttons */}
        <div className="flex gap-2 mt-4">
          <button
            onClick={() => onVote("up")}
            disabled={isReplacing || vote === "down"}
            className={`flex-1 py-2.5 rounded-lg transition font-bold ${
              vote === "up"
                ? "bg-green-600 text-white shadow-lg"
                : "bg-gray-700 hover:bg-green-600 text-white hover:shadow-lg"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            👍 {vote === "up" && "✓"}
          </button>

          <button
            onClick={() => {
              onVote("down");
              onReplace();
            }}
            disabled={isReplacing || vote === "up"}
            className={`flex-1 py-2.5 rounded-lg transition font-bold ${
              vote === "down"
                ? "bg-red-600 text-white shadow-lg"
                : "bg-gray-700 hover:bg-red-600 text-white hover:shadow-lg"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            👎 {isReplacing && "..."}
          </button>
        </div>

        {/* Spotify link */}
        {track.external_url && (
          <a
            href={track.external_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block mt-3 text-sm text-blue-400 hover:text-blue-300 hover:underline text-center font-semibold"
          >
            Open in Spotify →
          </a>
        )}
      </div>
    </div>
  );
}