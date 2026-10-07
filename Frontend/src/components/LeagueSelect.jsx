/**
 * The first screen after signing in: which league is this session for?
 *
 * At the top, the champions across every school. Then the schools, each a
 * tile in its own colours; choosing one shows its two leagues - billiards
 * and ping pong - and dresses the whole page in that school's colours
 * (onPreview), so the choice and the league look like one thing before
 * it's even made. The player's standing in each league they're in is
 * shown once their profile has loaded, and a league whose PIN they
 * haven't entered says so: they can still go in and look.
 */
import React, { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';

import { leagueColors } from '../leagueColors.js';
import { bySchool, gameInfo } from '../leagues.js';
import { GlobalLeaderboard } from './GlobalLeaderboard.jsx';

/** The colour roles a tile or option is drawn in, as inline CSS variables. */
function optionStyle(league, theme) {
  const colors = leagueColors(league.primary_color, league.secondary_color, theme);
  return {
    '--opt-bg': colors['panel-bg'],
    '--opt-text': colors['panel-text'],
    '--opt-dim': colors['panel-dim'],
    '--opt-edge': colors['panel-edge'],
    '--opt-border': colors['panel-border'],
    '--opt-shadow': colors['panel-shadow'],
    '--opt-ball': colors['panel-cta-bg'],
    '--opt-focus': colors['panel-focus'],
  };
}

export function LeagueSelect({
  current,
  leagues,
  profile,
  theme = 'light',
  champions,
  currentUserId,
  onChoose,
  onPreview = () => {},
}) {
  const schools = bySchool(leagues);
  const currentSchool = leagues?.find((l) => l.league_id === current)?.school ?? null;
  // The school whose leagues are showing: the current league's at first.
  const [picked, setPicked] = useState(null);
  const school = picked ?? currentSchool;
  const group = schools.find((g) => g.school === school) ?? null;

  // The page wears the school being looked at; back to the league's own
  // colours when the picker closes.
  const previewId = group?.leagues[0]?.league_id ?? null;
  useEffect(() => {
    onPreview(group ? group.leagues[0] : null);
    // Keyed on the league, not the group object, which every reload replaces.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewId]);
  useEffect(() => () => onPreview(null), [onPreview]);

  return (
    <main className="league-select" aria-labelledby="league-select-title">
      <GlobalLeaderboard champions={champions} currentUserId={currentUserId} />

      <div className="league-select-head">
        <h2 className="league-select-title" id="league-select-title">
          Which league are you playing?
        </h2>
        <p className="muted">
          Pick your school, then billiards or ping pong. This sets the queue, scores and ladder you
          see; you can switch any time from the top of the page.
        </p>
      </div>

      {!leagues && <p className="empty">Loading the leagues...</p>}

      {leagues && (
        <div className="school-grid" role="group" aria-label="Schools">
          {schools.map((g) => {
            const first = g.leagues[0];
            const isCurrent = g.school === currentSchool;
            return (
              <button
                key={g.school}
                type="button"
                className="school-tile"
                style={optionStyle(first, theme)}
                aria-pressed={g.school === school}
                onClick={() => setPicked(g.school)}
              >
                <span className="school-tile-name">{g.school}</span>
                <span className="school-tile-games">
                  {g.leagues.map((l) => gameInfo(l.game).name).join(' · ')}
                </span>
                {isCurrent && <span className="school-tile-current">Yours now</span>}
              </button>
            );
          })}
        </div>
      )}

      {group && (
        <section className="league-school" aria-labelledby="league-school-name">
          <h3 className="league-school-name" id="league-school-name">
            {group.school}
          </h3>
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
      )}

      {leagues && !group && (
        <p className="muted league-select-hint">Choose a school to see its leagues.</p>
      )}
    </main>
  );
}

function LeagueOption({ league, theme, current, standing, onChoose }) {
  const tables = league.tables || [];
  // A league with no table can't be played yet.
  const noTable = tables.length === 0;

  return (
    <button
      type="button"
      className="league-option"
      style={optionStyle(league, theme)}
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
