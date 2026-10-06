/**
 * The players of the month, the week and the day, on the status panel's
 * empty side: each one's picture, big, with their name underneath - the
 * month in the middle and highest, like a podium.
 *
 * "Best" is whoever gained the most points in that stretch of the
 * calendar (GET /top-players explains the rules). A picture or name
 * opens the player's profile. A period nobody has won a game in yet
 * says so, and how to take it.
 *
 * Drawn only in the panel's own colours (--panel-*), so it suits both
 * leagues and both themes without knowing which it's in.
 */
import React from 'react';
import { Trophy } from 'lucide-react';

import { flagEmoji } from '../flags.js';
import { useOpenPlayer } from '../openPlayer.js';
import { Avatar } from './Player.jsx';

// Screen-reader and DOM order: the month first, the biggest honour.
// Where each one sits is the stylesheet's business (.podium).
const SPOTS = [
  { period: 'month', title: 'Player of the month', empty: 'Win a game this month to take it.' },
  { period: 'week', title: 'Player of the week', empty: 'Win a game this week to take it.' },
  { period: 'day', title: 'Player of the day', empty: 'Win a game today to take it.' },
];

export function Podium({ topPlayers }) {
  return (
    <aside className="podium" aria-label="Players of the month, week and day">
      {SPOTS.map((spot) => (
        <Spot key={spot.period} {...spot} award={topPlayers[spot.period]} />
      ))}
    </aside>
  );
}

function Spot({ period, title, empty, award }) {
  const openPlayer = useOpenPlayer();
  const player = award?.player;
  const flag = flagEmoji(player?.country_flag);
  const featured = period === 'month';

  return (
    <div className="podium-spot" data-period={period}>
      <p className="podium-title">
        {featured && <Trophy size={13} aria-hidden="true" />}
        {title}
      </p>

      {player ? (
        <>
          <button
            type="button"
            className="podium-player"
            onClick={() => openPlayer?.(player.user_id)}
            disabled={!openPlayer}
            title={`See ${player.username}'s profile`}
          >
            <Avatar player={player} size={featured ? 'podium-lg' : 'podium'} />
            <span className="podium-name">
              <span className="podium-name-text">{player.username}</span>
              {flag && (
                <span className="podium-flag" aria-hidden="true">
                  {flag}
                </span>
              )}
            </span>
          </button>
          {/* Two pieces that each stay whole, so a narrow column breaks
              between them rather than inside "2-0". */}
          <p className="podium-stat">
            <span className="podium-points">
              {award.points >= 0 ? '+' : ''}
              {award.points} points
            </span>
            <span className="podium-record" aria-hidden="true">
              {award.wins}&ndash;{award.losses}
            </span>
            <span className="sr-only">
              , won {award.wins}, lost {award.losses}
            </span>
          </p>
        </>
      ) : (
        <>
          <span className="podium-empty" data-size={featured ? 'lg' : 'md'} aria-hidden="true">
            <Trophy size={featured ? 34 : 26} />
          </span>
          <p className="podium-name podium-name-empty">Nobody yet</p>
          <p className="podium-stat">{empty}</p>
        </>
      )}
    </div>
  );
}
