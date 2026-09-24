/**
 * The first screen after signing in: which league is this session for?
 *
 * Each option previews its league's colours, so the choice and the screen
 * that follows it look like the same thing. The player's standing in each
 * league is shown when their profile has loaded.
 */
import React from 'react';

import { LEAGUE_ORDER, LEAGUES } from '../leagues.js';

export function LeagueSelect({ current, profile, leagueTables, onChoose }) {
  return (
    <main className="league-select" aria-labelledby="league-select-title">
      <div className="league-select-head">
        <h2 className="league-select-title" id="league-select-title">
          Which league are you playing?
        </h2>
        <p className="muted">
          This sets the queue, scores and ladder you see. You can switch any time from the top
          of the page.
        </p>
      </div>

      <div className="league-options">
        {LEAGUE_ORDER.map((key) => {
          const info = LEAGUES[key];
          const standing = profile?.leagues?.[key];
          const table = leagueTables?.[key];
          // A league the venue hasn't given a table can't be played yet.
          const noTable = leagueTables && !table?.table_id;

          return (
            <button
              key={key}
              type="button"
              className="league-option"
              data-league-option={key}
              aria-current={current === key ? 'true' : undefined}
              disabled={noTable}
              onClick={() => onChoose(key)}
            >
              <span className="league-ball" data-ball={key} aria-hidden="true" />
              <span className="league-option-name">{info.name}</span>
              <span className="league-option-blurb">{info.blurb}</span>

              {standing && (
                <span className="league-option-standing">
                  <strong>{standing.rank_name}</strong>
                  <span>{standing.elo} points</span>
                  <span>
                    {standing.wins}&ndash;{standing.losses}
                  </span>
                </span>
              )}

              <span className="league-option-foot">
                {noTable ? 'No table set up yet' : table?.table_name ? `Plays on ${table.table_name}` : ''}
                {current === key && <span className="league-option-current">Current</span>}
              </span>
            </button>
          );
        })}
      </div>
    </main>
  );
}
