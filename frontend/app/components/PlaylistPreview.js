// NEW COMPONENT: components/PlaylistPreview.jsx
// Create this file in your frontend

import { useState } from "react";
import Image from "next/image";

export default function PlaylistPreview({ 
  sessionId, 
  initialTracks, 
  username,
  onFinalize 
}) {
  const [tracks, setTracks] = useState(initialTracks);
  const [votes, setVotes] = useState({}); // {uri: 'up'|'down'}
  const [replacing, setReplacing] = useState({}); // {uri: boolean}
  const [replacementsAvailable, setReplacementsAvailable] = useState(
    initialTracks.length * 2 // Estimate
  );

  const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

  // Handle thumbs up
  const handleThumbsUp = (trackUri) => {
    setVotes(prev => ({ ...prev, [trackUri]: 'up' }));
  };

  // Handle thumbs down - replace track
  const handleThumbsDown = async (trackUri) => {
    setReplacing(prev => ({ ...prev, [trackUri]: true }));
    setVotes(prev => ({ ...prev, [trackUri]: 'down' }));

    try {
      const res = await fetch(
        `${API_BASE}/playlist/replace-track?session_id=${sessionId}&track_uri=${encodeURIComponent(trackUri)}&username=${username}`,
        { method: 'POST' }
      );

      if (!res.ok) {
        const error = await res.json();
        alert(error.detail || 'Failed to replace track');
        setReplacing(prev => ({ ...prev, [trackUri]: false }));
        return;
      }

      const data = await res.json();
      
      // Replace track in list
      setTracks(prev => 
        prev.map(track => 
          track.uri === trackUri ? data.replacement_track : track
        )
      );
      
      // Clear vote for new track
      setVotes(prev => {
        const newVotes = { ...prev };
        delete newVotes[trackUri];
        return newVotes;
      });
      
      setReplacementsAvailable(data.replacements_remaining);
      
    } catch (err) {
      console.error('Replace failed:', err);
      alert('Network error replacing track');
    } finally {
      setReplacing(prev => ({ ...prev, [trackUri]: false }));
    }
  };

  // Handle finalize
  const handleFinalize = async () => {
    if (Object.values(votes).some(v => v === 'down')) {
      alert('Please replace all thumbs-down tracks before finalizing');
      return;
    }

    try {
      const res = await fetch(
        `${API_BASE}/playlist/finalize?session_id=${sessionId}&username=${username}`,
        { method: 'POST' }
      );

      if (!res.ok) {
        const error = await res.json();
        alert(error.detail || 'Failed to create playlist');
        return;
      }

      const data = await res.json();
      onFinalize(data.playlist_url);
      
    } catch (err) {
      console.error('Finalize failed:', err);
      alert('Network error creating playlist');
    }
  };

  const allApproved = tracks.every(track => votes[track.uri] === 'up');
  const hasVotes = Object.keys(votes).length > 0;

  return (
    <div className="w-full max-w-6xl mx-auto p-6">
      <div className="mb-6">
        <h2 className="text-2xl font-bold mb-2">Preview Your Playlist</h2>
        <p className="text-gray-600">
          Vote on each track. Thumbs down will instantly replace it with a new suggestion.
        </p>
        {replacementsAvailable > 0 && (
          <p className="text-sm text-gray-500 mt-1">
            {replacementsAvailable} replacement{replacementsAvailable !== 1 ? 's' : ''} available
          </p>
        )}
      </div>

      {/* Track Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {tracks.map((track) => (
          <TrackCard
            key={track.uri}
            track={track}
            vote={votes[track.uri]}
            isReplacing={replacing[track.uri]}
            onThumbsUp={() => handleThumbsUp(track.uri)}
            onThumbsDown={() => handleThumbsDown(track.uri)}
          />
        ))}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-4 justify-center">
        <button
          onClick={handleFinalize}
          disabled={!allApproved || !hasVotes}
          className={`px-6 py-3 rounded-lg font-semibold transition ${
            allApproved && hasVotes
              ? 'bg-green-600 hover:bg-green-700 text-white'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          {allApproved && hasVotes ? 'Create Playlist ✓' : 'Vote on All Tracks First'}
        </button>
      </div>
    </div>
  );
}

// Individual track card component
function TrackCard({ track, vote, isReplacing, onThumbsUp, onThumbsDown }) {
  const formatDuration = (ms) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  return (
    <div 
      className={`relative border rounded-lg overflow-hidden transition-all ${
        isReplacing ? 'opacity-50 scale-95' : 'opacity-100 scale-100'
      } ${
        vote === 'up' ? 'ring-2 ring-green-500' : 
        vote === 'down' ? 'ring-2 ring-red-500' : 
        'hover:shadow-lg'
      }`}
    >
      {/* Album Art */}
      <div className="relative w-full h-48 bg-gray-200">
        {track.album.image ? (
          <Image
            src={track.album.image}
            alt={track.album.name}
            fill
            className="object-cover"
            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-400">
            No Image
          </div>
        )}
        
        {/* Replacing overlay */}
        {isReplacing && (
          <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
            <div className="text-white text-sm">Finding replacement...</div>
          </div>
        )}
      </div>

      {/* Track Info */}
      <div className="p-4">
        <h3 className="font-semibold text-sm mb-1 line-clamp-1" title={track.name}>
          {track.name}
        </h3>
        <p className="text-xs text-gray-600 mb-1 line-clamp-1">
          {track.artists.map(a => a.name).join(', ')}
        </p>
        <p className="text-xs text-gray-500 mb-3">
          {track.album.name} • {formatDuration(track.duration_ms)}
        </p>

        {/* Vote Buttons */}
        <div className="flex gap-2">
          <button
            onClick={onThumbsUp}
            disabled={isReplacing || vote === 'down'}
            className={`flex-1 py-2 rounded transition ${
              vote === 'up'
                ? 'bg-green-500 text-white'
                : 'bg-gray-100 hover:bg-green-50 text-gray-700'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            👍 {vote === 'up' && 'Approved'}
          </button>
          
          <button
            onClick={onThumbsDown}
            disabled={isReplacing || vote === 'up'}
            className={`flex-1 py-2 rounded transition ${
              vote === 'down'
                ? 'bg-red-500 text-white'
                : 'bg-gray-100 hover:bg-red-50 text-gray-700'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            👎 {isReplacing ? 'Replacing...' : vote === 'down' ? 'Rejected' : ''}
          </button>
        </div>

        {/* Spotify Link */}
        {track.external_url && (
          <a
            href={track.external_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block mt-2 text-xs text-blue-600 hover:underline text-center"
          >
            Open in Spotify →
          </a>
        )}
      </div>
    </div>
  );
}