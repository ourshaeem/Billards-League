/**
 * How a player appears anywhere other people can see them: picture (or
 * initials), name and flag - and, on hover, their standing in the league
 * being shown.
 *
 * Everything here draws from a "player card" the backend sends with the
 * data (see Player.to_card in Backend/models.py), so hovering never
 * triggers a request.
 */
import React, { useEffect, useId, useRef, useState } from 'react';

import { flagEmoji } from '../flags.js';
import { leagueInfo } from '../leagues.js';

function initialOf(name) {
  const first = Array.from((name || '').trim())[0];
  return first ? first.toUpperCase() : '?';
}

/**
 * The player's picture, or their initial when there isn't one - or when
 * the link turns out to be broken, which a pasted URL often is.
 *
 * Decorative by default, because a name sits beside it. Pass `label` when
 * it stands alone.
 */
export function Avatar({ player, size = 'md', label }) {
  const src = player?.profile_picture || null;
  // Keyed on the link, so a new link gets a fresh try after an old one failed.
  return (
    <AvatarImage key={src || 'none'} src={src} name={player?.username} size={size} label={label} />
  );
}

function AvatarImage({ src, name, size, label }) {
  const [failed, setFailed] = useState(false);
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true };

  return (
    <span className="avatar" data-size={size} {...a11y}>
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          // Other people's image hosts don't need to know who's looking.
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        initialOf(name)
      )}
    </span>
  );
}

/**
 * Avatar, name and flag, with a card showing the player's rank, rating
 * and record in `league`.
 *
 * The card opens on mouse hover, on keyboard focus, and on tap - touch
 * screens have no hover, and without the tap a phone could never see it.
 * Escape, tapping elsewhere or moving away closes it.
 */
export function PlayerChip({ player, league, size = 'md', align = 'start', isYou = false }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  // How the current press started. Mouse and keyboard already opened the
  // card by hovering or focusing, so only a touch should toggle it.
  const pressRef = useRef(null);
  const tooltipId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!player) return null;

  const flag = flagEmoji(player.country_flag);
  const wins = player.wins ?? 0;
  const losses = player.losses ?? 0;

  return (
    <span
      className="player-chip"
      data-align={align}
      ref={wrapRef}
      onPointerEnter={(e) => {
        if (e.pointerType === 'mouse') setOpen(true);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === 'mouse') setOpen(false);
      }}
    >
      <button
        type="button"
        className="player-trigger"
        data-you={isYou ? 'true' : undefined}
        aria-describedby={open ? tooltipId : undefined}
        onPointerDown={(e) => {
          pressRef.current = e.pointerType;
        }}
        onFocus={() => {
          if (pressRef.current === null) setOpen(true);
        }}
        onBlur={() => {
          pressRef.current = null;
          setOpen(false);
        }}
        onClick={(e) => {
          const press = pressRef.current;
          pressRef.current = null;
          // e.detail is 0 for a click made with Enter or Space.
          if (press === 'mouse' || e.detail === 0) return;
          setOpen((current) => !current);
        }}
      >
        <Avatar player={player} size={size} />
        <span className="player-name">{player.username}</span>
        {isYou && <span className="sr-only"> (you)</span>}
        {flag && <span className="player-flag">{flag}</span>}
      </button>

      {open && (
        <span className="player-tooltip" role="tooltip" id={tooltipId}>
          <span className="tooltip-league">{leagueInfo(league).name}</span>
          {/* The name again: a long one may be cut short in the row. */}
          <span className="tooltip-name">
            {player.username} {flag}
          </span>
          <span className="tooltip-rank">{player.rank_name || 'Unranked'}</span>
          <span className="tooltip-elo">
            <strong>{player.elo ?? 0}</strong> points
          </span>
          <span className="tooltip-record">
            {wins} won &middot; {losses} lost
          </span>
        </span>
      )}
    </span>
  );
}
