/**
 * Who is at the table right now - for everyone, not just the two
 * players. The status panel answers "can I play?"; this answers "who's
 * on?", with each player's rank and rating a hover away, and their
 * profile a click.
 *
 * For the organiser (onRemove given), each player has a Remove button.
 */
import React, { useState } from 'react';
import { Crown, Swords } from 'lucide-react';

import { RemoveButton, RemoveConfirm } from './AdminControls.jsx';
import { NameBadge } from './Badges.jsx';
import { PlayerChip } from './Player.jsx';

const STATE_LABEL = {
  free: 'Free',
  waiting_for_challenger: 'Waiting',
  playing: 'Game on',
};

/** What taking `player` off the table does, in a sentence. */
function removalConsequence(table, player) {
  if (table.state !== 'playing') return 'The table goes to the next in the queue.';
  const other = player.user_id === table.king?.user_id ? table.challenger : table.king;
  const name = other?.username ?? 'the other player';
  return `Their game with ${name} is called off - nothing is recorded and no points move - and ${name} keeps the table.`;
}

export function ActiveTableCard({
  table,
  loaded,
  league,
  tableName,
  currentUserId,
  onRemove = null,
  busy = false,
}) {
  const state = table?.state;
  // { userId, matchId } of the player the organiser is asking to remove.
  // Tied to the game it was asked about: once that game is over, the
  // question no longer applies.
  const [asking, setAsking] = useState(null);
  const asked =
    asking && table?.match_id === asking.matchId
      ? [table.king, table.challenger].find((p) => p?.user_id === asking.userId)
      : null;

  const removal = (player) =>
    onRemove && player
      ? {
          expanded: asked?.user_id === player.user_id,
          onAsk: () =>
            setAsking(
              asked?.user_id === player.user_id
                ? null
                : { userId: player.user_id, matchId: table.match_id },
            ),
        }
      : null;

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
            badge={table.king_badge}
            league={league}
            currentUserId={currentUserId}
            removal={removal(table.king)}
          />
          <span className="matchup-vs" aria-hidden="true">
            vs
          </span>
          {table.challenger ? (
            <Seat
              label="Challenger"
              player={table.challenger}
              badge={table.challenger_badge}
              league={league}
              currentUserId={currentUserId}
              align="end"
              removal={removal(table.challenger)}
            />
          ) : (
            <div className="seat seat-empty" data-align="end">
              <span className="seat-label">Challenger</span>
              <span className="seat-waiting">Next in the queue</span>
            </div>
          )}
        </div>
      )}

      {asked && (
        <RemoveConfirm
          id="remove-from-table"
          triggerId={`remove-seat-${asked.user_id}`}
          question={`Take ${asked.username} off the table?`}
          consequence={removalConsequence(table, asked)}
          busy={busy}
          onCancel={() => setAsking(null)}
          onConfirm={async () => {
            await onRemove(asked, table.match_id);
            setAsking(null);
          }}
        />
      )}

      {loaded && table?.king_streak >= 2 && (
        <p className="small muted matchup-streak">
          {table.king.username} has won {table.king_streak} in a row
          {table.king_streak >= (table.table_record_streak ?? 0)
            ? ' - the table record.'
            : `. The table record is ${table.table_record_streak}.`}
        </p>
      )}
      {loaded && !(table?.king_streak >= 2) && table?.table_record_streak >= 2 && (
        <p className="small muted matchup-streak">
          Table record: {table.table_record_streak} wins in a row.
        </p>
      )}

      {loaded && state && state !== 'free' && (
        <p className="small muted card-foot">
          Hover over a player for their rank and rating, or click for their profile.
        </p>
      )}
    </section>
  );
}

function Seat({ label, crown = false, player, badge, league, currentUserId, align = 'start', removal }) {
  return (
    <div className="seat" data-align={align}>
      <span className="seat-label">
        {crown && <Crown size={14} aria-hidden="true" className="seat-crown" />}
        {label}
      </span>
      <span className="seat-player">
        <PlayerChip
          player={player}
          league={league}
          size="lg"
          align={align}
          isYou={player?.user_id === currentUserId}
        />
        <NameBadge badge={badge} size={26} />
      </span>
      {removal && (
        <RemoveButton
          id={`remove-seat-${player.user_id}`}
          name={player.username}
          place="the table"
          expanded={removal.expanded}
          controls="remove-from-table"
          onClick={removal.onAsk}
        />
      )}
    </div>
  );
}
