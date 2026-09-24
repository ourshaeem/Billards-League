/**
 * Finished games in this league, newest first - everyone's, or just
 * yours. Each player's rank and rating is on their hover card.
 */
import React, { useState } from 'react';
import { History } from 'lucide-react';

import { PlayerChip } from './Player.jsx';

const SCOPES = [
  { key: 'all', label: 'Everyone' },
  { key: 'mine', label: 'Your games' },
];

/**
 * "5m ago" from a count of seconds. The server works the seconds out with
 * its own clock, so a browser whose clock or timezone is off still shows
 * the right answer.
 */
function timeAgo(seconds) {
  if (typeof seconds !== 'number') return '';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(Date.now() - seconds * 1000).toLocaleDateString();
}

export function MatchHistoryCard({ history, loaded, league, currentUserId }) {
  const [scope, setScope] = useState('all');
  const matches = (scope === 'mine' ? history.mine : history.all) || [];

  return (
    <section className="card" aria-labelledby="history-heading">
      <div className="card-head">
        <h2 className="card-title" id="history-heading">
          <History size={18} aria-hidden="true" className="card-title-icon" />
          Recent games
        </h2>
        <div className="segmented" role="group" aria-label="Whose games to show">
          {SCOPES.map((option) => (
            <button
              key={option.key}
              type="button"
              className="segmented-option"
              aria-pressed={scope === option.key}
              onClick={() => setScope(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {!loaded && <p className="empty">Loading recent games...</p>}

      {loaded && matches.length === 0 && (
        <p className="empty">
          {scope === 'mine'
            ? "You haven't finished a game in this league yet."
            : 'No games finished yet. The first result shows up here.'}
        </p>
      )}

      {loaded && matches.length > 0 && (
        <ol className="history-list">
          {matches.map((match) => (
            <HistoryRow
              key={match.match_id}
              match={match}
              league={league}
              currentUserId={currentUserId}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

function HistoryRow({ match, league, currentUserId }) {
  const { winner, loser, winner_score: won, loser_score: lost, result } = match;
  const hasScore = typeof won === 'number' && typeof lost === 'number';
  const change = match.elo_change;

  return (
    <li className="history-row" data-result={result || undefined}>
      <div className="history-players">
        <div className="history-side">
          <PlayerChip
            player={winner}
            league={league}
            size="sm"
            isYou={winner?.user_id === currentUserId}
          />
          <span className="result-tag" data-result="win">
            Winner
          </span>
        </div>

        <p className="history-score">
          <span className="sr-only">Score: </span>
          {hasScore ? (
            <>
              <span className="history-score-win">{won}</span>
              <span aria-hidden="true">&ndash;</span>
              <span className="sr-only"> to </span>
              <span>{lost}</span>
            </>
          ) : (
            <span className="muted">&mdash;</span>
          )}
        </p>

        <div className="history-side" data-align="end">
          <PlayerChip
            player={loser}
            league={league}
            size="sm"
            align="end"
            isYou={loser?.user_id === currentUserId}
          />
          <span className="result-tag" data-result="loss">
            Loser
          </span>
        </div>
      </div>

      <p className="history-meta">
        {result && (
          <strong className="history-outcome" data-result={result}>
            {result === 'won' ? 'You won' : 'You lost'}
            {typeof change === 'number' && ` ${result === 'won' ? '+' : '−'}${change}`}
          </strong>
        )}
        {!result && typeof change === 'number' && <span>&plusmn;{change} points</span>}
        <span>{timeAgo(match.seconds_ago)}</span>
      </p>
    </li>
  );
}
