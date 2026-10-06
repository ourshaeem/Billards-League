/**
 * The first screen after signing in: which league is this session for?
 *
 * Every league, grouped by school. Each option previews its league's own
 * colours - built the same way as the screen that follows, so the choice
 * and the league look like one thing. The player's standing in each
 * league they're in is shown once their profile has loaded, and a league
 * whose PIN they haven't entered says so: they can still go in and look.
 */
import React from 'react';
import { Lock } from 'lucide-react';

import { leagueColors } from '../leagueColors.js';
import { bySchool, gameInfo } from '../leagues.js';

export function LeagueSelect({ current, leagues, profile, theme = 'light', onChoose }) {
  if (!leagues) {
    return (
      <main className="league-select">
        <p className="empty">Loading the leagues...</p>
      </main>
    );
  }

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

      {bySchool(leagues).map((group) => (
        <section className="league-school" key={group.school} aria-label={group.school}>
          <h3 className="league-school-name">{group.school}</h3>
          <div className="league-options">
            {group.leagues.map((league) => (
              <LeagueOption
                key={league.league_id}
                league={league}
                theme={theme}
                current={current === league.league_id}
                standing={profile?.standings?.find((s) => s.league_id === league.league_id)}
                onChoose={onChoose}
              />
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}

function LeagueOption({ league, theme, current, standing, onChoose }) {
  const colors = leagueColors(league.primary_color, league.secondary_color, theme);
  const tables = league.tables || [];
  // A league with no table can't be played yet.
  const noTable = tables.length === 0;
  const style = {
    '--opt-bg': colors['panel-bg'],
    '--opt-text': colors['panel-text'],
    '--opt-edge': colors['panel-edge'],
    '--opt-border': colors['panel-border'],
    '--opt-shadow': colors['panel-shadow'],
    '--opt-ball': colors['panel-cta-bg'],
    '--opt-focus': colors['panel-focus'],
  };

  return (
    <button
      type="button"
      className="league-option"
      style={style}
      aria-current={current ? 'true' : undefined}
      disabled={noTable}
      onClick={() => onChoose(league.league_id)}
    >
      <span className="league-ball" data-ball={league.game} aria-hidden="true" />
      <span className="league-option-name">{league.name}</span>
      <span className="league-option-blurb">{gameInfo(league.game).blurb}</span>

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
        <span>
          {noTable
            ? 'No table set up yet'
            : tables.length === 1
              ? `Plays on ${tables[0].table_name}`
              : `${tables.length} tables`}
        </span>
        {league.read_only && (
          <span className="league-option-lock">
            <Lock size={13} aria-hidden="true" />
            {league.has_pin ? 'PIN needed to play' : 'No PIN set yet'}
          </span>
        )}
        {current && <span className="league-option-current">Current</span>}
      </span>
    </button>
  );
}
