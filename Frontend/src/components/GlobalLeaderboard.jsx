/**
 * The champions across every school, at the top of the league picker: the
 * top 3 in billiards or ping pong this week, this month and of all time,
 * whichever league they play in (GET /leaderboard/global). Seen before
 * choosing a league, so a player knows who's on top everywhere.
 *
 * This week and this month rank by rating points gained; all time by the
 * best rating anyone holds. Each name opens that player's profile.
 */
import React, { useState } from 'react';
import { Trophy } from 'lucide-react';

import { LEAGUE_ORDER, gameInfo } from '../leagues.js';
import { PlayerChip } from './Player.jsx';

const TIMEFRAMES = [
  { key: 'week', label: 'This week' },
  { key: 'month', label: 'This month' },
  { key: 'all_time', label: 'All time' },
];

function signed(points) {
  return points > 0 ? `+${points}` : String(points);
}

export function GlobalLeaderboard({ champions, currentUserId }) {
  const [game, setGame] = useState(LEAGUE_ORDER[0]);
  const board = champions?.sports?.[game] ?? null;

  return (
    <section className="card champions" aria-labelledby="champions-title">
      <div className="champions-head">
        <h2 className="champions-title" id="champions-title">
          <Trophy size={20} aria-hidden="true" className="card-title-icon" />
          Champions across every school
        </h2>
        <div className="segmented" role="group" aria-label="Which game's champions">
          {LEAGUE_ORDER.map((key) => (
            <button
              key={key}
              type="button"
              className="segmented-option"
              aria-pressed={game === key}
              onClick={() => setGame(key)}
            >
              {gameInfo(key).name}
            </button>
          ))}
        </div>
      </div>

      {!champions && <p className="empty">Loading the champions...</p>}

      {board && (
        <div className="champions-grid">
          {TIMEFRAMES.map(({ key, label }) => {
            const places = board[key] || [];
            return (
              <div className="champions-period" key={key}>
                <h3 className="champions-period-title">{label}</h3>
                {places.length === 0 ? (
                  <p className="small muted champions-empty">
                    {key === 'all_time' ? 'No games played yet.' : 'Nobody has won a game yet.'}
                  </p>
                ) : (
                  <ol className="champions-list">
                    {places.map((place) => (
                      <li className="champion" data-place={place.place} key={place.player.user_id}>
                        <span className="champion-place" aria-label={`Number ${place.place}`}>
                          {place.place}
                        </span>
                        <span className="champion-who">
                          <PlayerChip
                            player={place.player}
                            league={{ league_id: place.league_id, name: place.league_name, game }}
                            size="sm"
                            isYou={place.player.user_id === currentUserId}
                          />
                          <span className="champion-school">{place.school}</span>
                        </span>
                        <span className="champion-value">
                          <span>
                            <strong>{key === 'all_time' ? place.elo : signed(place.points)}</strong>{' '}
                            pts
                          </span>
                          <span className="champion-record">
                            {place.wins}&ndash;{place.losses}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="small muted card-foot">
        This week and this month: most points gained, in every school&rsquo;s league. All time:
        the best rating anyone holds.
      </p>
    </section>
  );
}
