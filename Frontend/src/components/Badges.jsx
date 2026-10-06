/**
 * Badges: the emblem each achievement shows, and the card listing a
 * player's badges in one league.
 *
 * Every achievement has its own icon - no two share one - set in a
 * medallion coloured by tier (bronze, silver, gold, legendary). Names,
 * rules and tiers come from the backend (logic/achievements.py), already
 * in the league's own words ("Bagel" in ping pong, "Shutout" in
 * billiards); this file only knows how each one looks.
 */
import React, { useEffect, useState } from 'react';
import {
  Award, Axe, Ban, BarChart3, Bird, Brush, CalendarCheck, CalendarDays, CalendarHeart,
  Castle, Cat, Check, ChessKing, CircleDot, Clover, Coins, Copy, Crosshair, Crown, Diamond,
  DoorOpen, Dumbbell, Eye, Flame, Footprints, Gauge, Gavel, Gem, Ghost, Gift, Hammer,
  Handshake, HeartCrack, HeartPulse, Hourglass, Infinity as InfinityIcon, Landmark, Lock,
  LogOut, Medal, Moon, MoonStar, Mountain, MountainSnow, Network, PartyPopper, Repeat2,
  Rocket, RotateCcw, Scale, Shield, ShieldCheck, Skull, Sparkles, Sprout, Squirrel, Star,
  Sunrise, Sword, Swords, Target, TrendingUp, Trophy, UserPlus, WandSparkles, Zap,
} from 'lucide-react';

import * as api from '../api.js';

const ICONS = {
  // Milestones
  first_break: CircleDot,
  regular: CalendarCheck,
  veteran: ShieldCheck,
  centurion: Landmark,
  lifer: InfinityIcon,
  hall_of_famer: Castle,
  // Wins
  first_blood: Sword,
  double_digits: Target,
  fifty_club: Medal,
  hundred_club: Trophy,
  // Never quit
  learning_curve: Sprout,
  thick_skin: Shield,
  phoenix: Bird,
  // Streaks
  bounce_back: RotateCcw,
  hat_trick: WandSparkles,
  on_fire: Flame,
  unstoppable: Rocket,
  untouchable: Zap,
  // King of the hill
  crowned: Crown,
  kingslayer: Axe,
  tyrant_toppler: Gavel,
  usurper: ChessKing,
  record_breaker: MountainSnow,
  // Scorelines
  shutout: Ban,
  shutout_artist: Brush,
  nail_biter: HeartPulse,
  so_close: HeartCrack,
  dominator: Hammer,
  // Upsets and rating
  giant_killer: Crosshair,
  david_vs_goliath: Mountain,
  underdog: Squirrel,
  big_payday: Coins,
  big_day: TrendingUp,
  century: Gauge,
  double_century: Gem,
  // The ladder
  rank_silver: Award,
  rank_gold: Star,
  rank_platinum: Diamond,
  podium: BarChart3,
  number_one: Sparkles,
  // Rivals
  social_butterfly: UserPlus,
  networker: Network,
  rivalry: Swords,
  nemesis: Skull,
  revenge: Eye,
  welcome_committee: Handshake,
  // Time and dedication
  early_bird: Sunrise,
  night_owl: Moon,
  marathon: Footprints,
  iron_man: Dumbbell,
  flawless_night: MoonStar,
  weekend_warrior: CalendarDays,
  loyal: CalendarHeart,
  welcome_back: DoorOpen,
  // Secrets
  deja_vu: Repeat2,
  perfectly_balanced: Scale,
  lucky_sevens: Clover,
  mirror_match: Copy,
  spooky: Ghost,
  ho_ho_ho: Gift,
  fresh_start: PartyPopper,
  friday_13th: Cat,
  abdication: LogOut,
  patience: Hourglass,
};

const TIER_LABEL = {
  bronze: 'Bronze',
  silver: 'Silver',
  gold: 'Gold',
  legendary: 'Legendary',
};

/**
 * The medallion. `locked` greys it out; a locked secret shows a padlock
 * instead of its icon, so the icon can't give the secret away.
 */
export function BadgeEmblem({ badgeKey, tier, size = 48, locked = false, secret = false, title }) {
  const Icon = locked && secret ? Lock : ICONS[badgeKey] || Award;
  return (
    <span
      className="badge-emblem"
      data-tier={tier}
      data-locked={locked ? 'true' : 'false'}
      style={{ '--emblem-size': `${size}px` }}
      title={title}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : 'true'}
    >
      <Icon size={Math.round(size * 0.5)} strokeWidth={2.2} aria-hidden="true" />
    </span>
  );
}

/** A small badge beside a player's name, from {key, name, tier}. */
export function NameBadge({ badge, size = 22 }) {
  if (!badge) return null;
  return (
    <BadgeEmblem
      badgeKey={badge.key}
      tier={badge.tier}
      size={size}
      title={`${badge.name} (${TIER_LABEL[badge.tier] || badge.tier})`}
    />
  );
}

function formatDate(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

const FILTERS = [
  ['all', 'All'],
  ['earned', 'Earned'],
  ['locked', 'Locked'],
];

/**
 * One player's badges in one league. Loads its own data; bump `version`
 * to load again (after a game, say). `onFeature` - given only for the
 * signed-in player's own card - lets them choose the badge by their name.
 */
export function BadgesCard({ userId, league, version = 0, title = 'Your badges', onFeature, busy }) {
  const [data, setData] = useState(null);
  const [problem, setProblem] = useState(null);
  const [filter, setFilter] = useState('all');
  const leagueId = league?.league_id;

  useEffect(() => {
    const controller = new AbortController();
    api.getPlayerBadges(userId, leagueId, controller.signal).then((res) => {
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && res.data) {
        setData(res.data);
        setProblem(null);
      } else {
        setProblem(res.message);
      }
    });
    return () => controller.abort();
  }, [userId, leagueId, version]);

  const head = (
    <div className="card-head">
      <h2 className="card-title" id={`badges-heading-${userId}`}>
        <Medal size={18} aria-hidden="true" className="card-title-icon" />
        {title}
      </h2>
      {data && (
        <span className="count-pill">
          {data.earned_count} / {data.total} earned
        </span>
      )}
    </div>
  );

  if (!data) {
    return (
      <section className="card badges-card" aria-labelledby={`badges-heading-${userId}`}>
        {head}
        <p className="empty">{problem || 'Loading badges...'}</p>
      </section>
    );
  }

  const byKey = Object.fromEntries(data.badges.map((b) => [b.key, b]));
  const featured = data.featured ? byKey[data.featured] : null;
  const visible = data.badges.filter(
    (b) => filter === 'all' || (filter === 'earned' ? b.earned : !b.earned),
  );

  return (
    <section className="card badges-card" aria-labelledby={`badges-heading-${userId}`}>
      {head}

      <div className="badges-toolbar">
        <p className="badges-featured">
          {featured ? (
            <>
              <BadgeEmblem badgeKey={featured.key} tier={featured.tier} size={28} />
              <span>
                {onFeature ? 'Showing ' : 'Shows '}
                <strong>{featured.name}</strong> next to {onFeature ? 'your' : 'their'} name
                {onFeature && !data.chosen ? ' (picked automatically)' : ''}.
              </span>
              {onFeature && data.chosen && (
                <button
                  type="button"
                  className="btn btn-quiet btn-small"
                  onClick={() => onFeature(null)}
                  disabled={busy}
                >
                  Pick automatically
                </button>
              )}
            </>
          ) : (
            <span className="muted">
              {onFeature ? 'Play a game to earn your first badge.' : 'No badges in this league yet.'}
            </span>
          )}
        </p>

        <div className="segmented" role="group" aria-label="Show badges">
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className="segmented-option"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {data.groups.map((group) => {
        const badges = visible.filter((b) => b.group === group.key);
        if (badges.length === 0) return null;
        const inGroup = data.badges.filter((b) => b.group === group.key);

        return (
          <div className="badge-group" key={group.key}>
            <h3 className="badge-group-title">
              {group.name}
              <span className="muted small">
                {inGroup.filter((b) => b.earned).length} / {inGroup.length}
              </span>
            </h3>
            <ul className="badge-grid">
              {badges.map((badge) => (
                <BadgeTile
                  key={badge.key}
                  badge={badge}
                  isFeatured={badge.key === data.featured}
                  isChosen={badge.key === data.chosen}
                  onFeature={onFeature}
                  busy={busy}
                />
              ))}
            </ul>
          </div>
        );
      })}

      {visible.length === 0 && (
        <p className="empty">
          {filter === 'earned' ? 'No badges here yet.' : 'Every badge earned. Legend.'}
        </p>
      )}
    </section>
  );
}

function BadgeTile({ badge, isFeatured, isChosen, onFeature, busy }) {
  const { progress } = badge;
  const percent = progress ? Math.round((progress.current / progress.target) * 100) : 0;

  return (
    <li className="badge-tile" data-earned={badge.earned ? 'true' : 'false'}>
      <BadgeEmblem
        badgeKey={badge.key}
        tier={badge.tier}
        size={52}
        locked={!badge.earned}
        secret={badge.secret}
      />
      <div className="badge-body">
        <p className="badge-name">
          {badge.name}
          <span className="badge-tier" data-tier={badge.tier}>
            {TIER_LABEL[badge.tier]}
          </span>
        </p>
        <p className="badge-desc">{badge.description}</p>

        {badge.earned && (
          <div className="badge-foot">
            <span className="small muted">Earned {formatDate(badge.earned_at)}</span>
            {onFeature &&
              (isChosen ? (
                <span className="badge-showing">
                  <Check size={14} aria-hidden="true" /> On your name
                </span>
              ) : (
                <button
                  type="button"
                  className="badge-feature"
                  onClick={() => onFeature(badge.key)}
                  disabled={busy}
                >
                  {isFeatured ? 'Keep on your name' : 'Show on your name'}
                </button>
              ))}
          </div>
        )}

        {!badge.earned && progress && (
          <div className="badge-progress">
            <div
              className="badge-progress-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={progress.target}
              aria-valuenow={progress.current}
              aria-label={`${badge.name} progress`}
            >
              <span style={{ width: `${percent}%` }} />
            </div>
            <span className="small muted">
              {progress.current} / {progress.target}
            </span>
          </div>
        )}
      </div>
    </li>
  );
}
