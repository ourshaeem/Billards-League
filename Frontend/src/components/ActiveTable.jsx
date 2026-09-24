/**
 * Who is at the table right now - for everyone, not just the two
 * players. The status panel answers "can I play?"; this answers "who's
 * on?", with each player's rank and rating a hover (or tap) away.
 */
import React from 'react';
import { Crown, Swords } from 'lucide-react';

import { PlayerChip } from './Player.jsx';

const STATE_LABEL = {
  free: 'Free',
  waiting_for_challenger: 'Waiting',
  playing: 'Game on',
};

export function ActiveTableCard({ table, loaded, league, tableName, currentUserId }) {
  const state = table?.state;

  return (
    <section className="card" aria-labelledby="table-heading">
      <div className="card-head">
        <h2 className="card-title" id="table-heading">
          <Swords size={18} aria-hidden="true" className="card-title-icon" />
          At the table
        </h2>
        {loaded && state && <span className="count-pill">{STATE_LABEL[state] ?? state}</span>}
      </div>

      {!loaded && <p className="empty">Checking the table...</p>}

      {loaded && state === 'free' && (
        <p className="empty">Nobody is on {tableName || 'the table'}. The first two in the queue play.</p>
      )}

      {loaded && (state === 'playing' || state === 'waiting_for_challenger') && (
        <div className="matchup">
          <Seat
            label="Holding the table"
            crown
            player={table.king}
            league={league}
            currentUserId={currentUserId}
          />
          <span className="matchup-vs" aria-hidden="true">
            vs
          </span>
          {table.challenger ? (
            <Seat
              label="Challenger"
              player={table.challenger}
              league={league}
              currentUserId={currentUserId}
              align="end"
            />
          ) : (
            <div className="seat seat-empty" data-align="end">
              <span className="seat-label">Challenger</span>
              <span className="seat-waiting">Next in the queue</span>
            </div>
          )}
        </div>
      )}

      {loaded && table?.king_streak >= 2 && (
        <p className="small muted matchup-streak">
          {table.king.username} has won {table.king_streak} in a row.
        </p>
      )}

      {loaded && state && state !== 'free' && (
        <p className="small muted card-foot">
          Hover over or tap a player to see their rank and rating.
        </p>
      )}
    </section>
  );
}

function Seat({ label, crown = false, player, league, currentUserId, align = 'start' }) {
  return (
    <div className="seat" data-align={align}>
      <span className="seat-label">
        {crown && <Crown size={14} aria-hidden="true" className="seat-crown" />}
        {label}
      </span>
      <PlayerChip
        player={player}
        league={league}
        size="lg"
        align={align}
        isYou={player?.user_id === currentUserId}
      />
    </div>
  );
}
