/**
 * Who is at the league's tables right now - for everyone, not just the
 * players. The status panel answers "can I play?"; this answers "who's
 * on?", table by table, with each player's rank and rating a hover away,
 * and their profile a click.
 *
 * For the organiser (onRemove given), each player has a Remove button.
 */
import React, { useState } from 'react';
import { Crown, Swords, Trophy } from 'lucide-react';

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

export function TablesCard({ tables, loaded, league, currentUserId, onRemove = null, busy = false }) {
  const many = tables.length > 1;
  const playing = tables.filter((t) => t.state !== 'free').length;

  return (
    <section className="card" aria-labelledby="tables-heading">
      <div className="card-head">
        <h2 className="card-title" id="tables-heading">
          <Swords size={18} aria-hidden="true" className="card-title-icon" />
          {many ? 'At the tables' : 'At the table'}
        </h2>
        {loaded && !many && tables[0] && (
          <span className="count-pill">{STATE_LABEL[tables[0].state] ?? tables[0].state}</span>
        )}
        {loaded && many && (
          <span className="count-pill">
            {playing} of {tables.length} in use
          </span>
        )}
      </div>

      {!loaded && <p className="empty">Checking the tables...</p>}

      {loaded &&
        tables.map((table) => (
          <TableBlock
            key={table.table_id}
            table={table}
            showName={many}
            league={league}
            currentUserId={currentUserId}
            onRemove={onRemove}
            busy={busy}
          />
        ))}

      {loaded && playing > 0 && (
        <p className="small muted card-foot">
          Hover over a player for their rank and rating, or click for their profile.
        </p>
      )}
    </section>
  );
}

function TableBlock({ table, showName, league, currentUserId, onRemove, busy }) {
  const state = table.state;
  // { userId, matchId } of the player the organiser is asking to remove.
  // Tied to the game it was asked about: once that game is over, the
  // question no longer applies.
  const [asking, setAsking] = useState(null);
  const asked =
    asking && table.match_id === asking.matchId
      ? [table.king, table.challenger].find((p) => p?.user_id === asking.userId)
      : null;
  const confirmId = `remove-from-table-${table.table_id}`;

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
    <div className="table-block" data-many={showName ? 'true' : 'false'}>
      {showName && (
        <div className="table-block-head">
          <h3 className="table-block-name">{table.table_name}</h3>
          <span className="table-block-state" data-state={state}>
            {STATE_LABEL[state] ?? state}
          </span>
        </div>
      )}

      {state === 'free' && (
        <p className="empty">
          Nobody is on {table.table_name}. The next two in the queue play here.
        </p>
      )}

      {(state === 'playing' || state === 'waiting_for_challenger') && (
        <div className="matchup">
          <Seat
            label="Holding the table"
            crown
            player={table.king}
            badge={table.king_badge}
            league={league}
            currentUserId={currentUserId}
            removal={removal(table.king)}
            tableId={table.table_id}
            confirmId={confirmId}
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
              tableId={table.table_id}
              confirmId={confirmId}
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
          id={confirmId}
          triggerId={`remove-seat-${table.table_id}-${asked.user_id}`}
          question={`Take ${asked.username} off ${table.table_name}?`}
          consequence={removalConsequence(table, asked)}
          busy={busy}
          onCancel={() => setAsking(null)}
          onConfirm={async () => {
            await onRemove(asked, table.match_id, table.table_id);
            setAsking(null);
          }}
        />
      )}

      {table.king_streak >= 2 && (
        <p className="small muted matchup-streak">
          {table.king.username} has won {table.king_streak} in a row
          {table.king_streak >= (table.table_record_streak ?? 0) ? ' - the table record.' : '.'}
        </p>
      )}
      <TableRecord table={table} league={league} currentUserId={currentUserId} />
    </div>
  );
}

/** The table's longest winning run, and whose it is - their picture and name. */
function TableRecord({ table, league, currentUserId }) {
  const record = table.table_record_streak ?? 0;
  const holder = table.table_record_holder;
  if (record < 2) return null;
  return (
    <div className="table-record">
      <Trophy size={16} aria-hidden="true" className="table-record-icon" />
      <span className="table-record-label">
        Table record: <strong>{record} wins in a row</strong>
        {holder ? ', by' : '.'}
      </span>
      {holder && (
        <PlayerChip
          player={holder}
          league={league}
          size="sm"
          isYou={holder.user_id === currentUserId}
        />
      )}
    </div>
  );
}

function Seat({
  label,
  crown = false,
  player,
  badge,
  league,
  currentUserId,
  align = 'start',
  removal,
  tableId,
  confirmId,
}) {
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
          id={`remove-seat-${tableId}-${player.user_id}`}
          name={player.username}
          place="the table"
          expanded={removal.expanded}
          controls={confirmId}
          onClick={removal.onAsk}
        />
      )}
    </div>
  );
}
