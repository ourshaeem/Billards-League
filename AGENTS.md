# Working agreement: the six roles

This file is the division of labour for the project, written down so that
a change made under one role doesn't quietly break another's work. Each
section says what that role owns, which files it touches, and what it
must not change alone.

**One honest note up front.** These are six *roles*, not six independent
programs running in the background. Whoever is working on this project -
you, a teammate, or an AI assistant - takes on the relevant role for the
task at hand. The value here is the boundaries and the handoff rule, not
a claim that six separate agents are running. Treating it as a checklist
is what keeps the seams from splitting.

---

## Shared rules (all roles)

1. **Tech stack is fixed:** MySQL, Python/Flask, React. No swapping in an
   ORM, a different database, or a new framework without agreement.
2. **A mobile port with React Native is coming.** Business rules live in
   the backend; the frontend's HTTP knowledge is confined to
   `Frontend/src/api.js`. Nothing else in the UI should call `fetch`.
   When the React Native app happens, that one file is the port.
3. **Run the backend tests before and after any change:**
   ```
   cd Backend && python -m unittest discover -s tests -t .
   ```
   All tests must pass. A new feature isn't done until it has one.
4. **The database is shared truth.** Any schema change goes through
   `ensure_schema()` in `Backend/database.py` so nobody has to run SQL by
   hand, and it must be safe to run repeatedly.
5. **Never trust the client for a rule.** Disabling a button is a
   courtesy; the endpoint must enforce the same rule.

---

## Backend 1 - errors, queue, matches, auth

**Owns:** everything that has broken before or could break again around
joining queues, starting and recording matches, logging in, registering.

**Files:** `Backend/app.py` (routes), `Backend/logic/manage_queue.py`,
`Backend/logic/record_match.py`, `Backend/logic/auth.py`,
`Backend/tests/`.

**Standing responsibilities**
- Every endpoint returns a message a person could read. No bare 500s, no
  `"Error: <stack trace>"` reaching the UI.
- Matchmaking has exactly one implementation:
  `manage_queue.attempt_matchmaking()`. If a second copy of that logic
  ever appears, that is the bug - a duplicate is what caused the original
  stuck-queue deadlock.
- Distinguishable outcomes stay distinguishable. `join_queue`,
  `step_down` and `report_result` return *which* thing happened, never a
  bare true/false.
- Anything that changes who is at a table takes that table's lock first
  (`_lock_table`), then uses `_locked()` reads, which also refresh
  SQLAlchemy's cached copy of the row. Skipping the refresh lets a
  request act on a row as it was before it waited for the lock.
- Functions that run their own transaction are wrapped in
  `retry_on_deadlock`, because MySQL cancels colliding transactions and
  expects them to be re-run.

**Inherits from Backend 3:** once a new feature has a passing test and is
working, it becomes this role's responsibility. Future breakage in it is
a Backend 1 job, not a Backend 3 job.

---

## Backend 2 - logistics and data

**Owns:** the database itself, configuration, dependencies, and how the
app gets run - locally and in production.

**Files:** `Backend/database.py`, `Backend/requirements.txt`,
`Backend/.env.example`, `.gitignore`, `Backend/Dockerfile`,
`Backend/.dockerignore`, `Backend/gunicorn.conf.py`, schema.

**Standing responsibilities**
- Schema migrations are additive and idempotent, in `ensure_schema()`.
- Secrets live in `Backend/.env`, never in source. (The old MySQL
  password and JWT key are still in this repo's git history - both should
  be rotated. Steps are in `Backend/.env.example`.)
- Dependencies stay pinned in `requirements.txt`. The MySQL driver is
  PyMySQL (`mysql+pymysql://`), locally and in production; anything that
  reads a MySQL error code goes through `mysql_error_code()`, because
  PyMySQL keeps it somewhere other drivers don't.
- Production configuration comes only from environment variables. The
  image sets `APP_ENV=production`, which turns a missing `DATABASE_URL`
  or `JWT_SECRET_KEY` into a refusal to start - never a quiet fallback to
  the local defaults. `ensure_schema()` runs once per start, via
  `flask prepare-db` in a separate process gunicorn launches before its
  workers - never per worker, and never inside gunicorn's master: workers
  are forks of the master, and a master that has opened a database
  connection makes them crash (seen on macOS). It must be able to build
  an empty database from nothing.
- Query performance: queue and match lookups filter on `table_id`,
  `user_id` and `match_status`. The indexes are declared on the models
  and `ensure_schema()` creates any that are missing.
- The models map the database that exists. `Matches` seats live in
  `king_id` / `challenger_id` (Python: `player_one_id` / `player_two_id`).
  `check_schema()` compares every mapped column with the real database at
  startup - a model column the database lacks is the bug that broke
  joining in round 2.

**Must not:** change an endpoint's request or response shape alone - that
is a contract with the frontend. See *Shared contracts* below.

---

## Backend 3 - new features

**Owns:** building things that don't exist yet.

**Standing responsibilities**
- A new feature ships with tests in `Backend/tests/`, covering the normal
  path and at least one failure.
- New endpoints follow the existing response shape (`message`, plus data
  keys) so `api.js` needs no special cases.
- **Handoff rule:** when the feature works and its test passes, ownership
  moves to Backend 1. Note the date and the test name in the pull request
  so the handoff is on the record.

**Candidate next features:** more than one table per league (the backend
accepts any `table_id`; the UI uses each league's first table), an admin
view to clear a stuck table, seasons.

**Shipped, handed to Backend 1 on 2026-09-23:** the ping pong league,
match history and player profiles. Tests: `tests/test_leagues.py`
(`LeagueRouting`, `PingPongRecording`, `PingPongScoreRules`,
`PingPongEloTests`, `LeaderboardByLeague`, `TableSnapshotRoute`),
`tests/test_match_history.py`, `tests/test_profile.py`, and the
`ensure_schema` additions in `tests/test_schema.py`.

---

## Frontend 1 - connections

**Owns:** making sure an action in the UI actually reaches the backend
and comes back.

**Files:** `Frontend/src/api.js`, the action handlers in
`Frontend/src/App.jsx`.

**Standing responsibilities**
- Every call goes through `api.js`. No `fetch` anywhere else.
- Every action refreshes the affected data afterwards, so the screen and
  the server agree.
- Polling cleans up after itself. Effects abort in-flight requests on
  unmount; no setState after unmount, no duplicate timers.
- Keep request and response shapes in step with the backend. When they
  change, they change on both sides in the same commit.

---

## Frontend 2 - errors between frontend and backend

**Owns:** what a person sees when something goes wrong.

**Files:** the error paths in `Frontend/src/api.js`,
`Frontend/src/components/Feedback.jsx`, per-field validation in
`Frontend/src/components/AuthScreens.jsx`.

**Standing responsibilities**
- Four failure kinds stay distinguishable: `NETWORK`, `AUTH`, `REJECTED`,
  `SERVER` (`ErrorKind` in `api.js`). A dropped wifi connection must not
  look like a rejected password.
- Expired sessions return the person to the sign-in screen rather than
  leaving dead buttons.
- No `alert()`. It blocks the tab and can't be styled.
- Validation messages appear beside the field they concern.
- When the backend explains a refusal, show its wording rather than
  inventing a vaguer one.

---

## Frontend 3 - look and feel

**Owns:** the visual design.

**Files:** `Frontend/src/index.css`, `Frontend/index.html`, markup and
class names in `Frontend/src/components/`.

**Standing responsibilities**
- Design tokens live in `:root` in `index.css`. Use the variables; don't
  hardcode colours in components.
- The palette is purple and white, with gray as the secondary colour.
  Red and amber are for errors and warnings only.
- Two league themes, chosen by `<html data-league>`: billiards (purple,
  white, gray - the default) and ping pong (white, purple, gray - the
  status panel turns white). A theme only redefines tokens, including
  the `--panel-*` roles the status panel uses; components never check
  which league they're drawn in.
- Quality floor, not negotiable: works down to a phone width, visible
  keyboard focus, readable contrast, `prefers-reduced-motion` respected.
- The status panel is the one loud element on the page. If something else
  starts competing with it, quiet that thing down.

**Must not:** change what a component *says* about state without checking
with Frontend 2, or rename props without checking with Frontend 1.

---

## Shared contracts

These are the seams. Changing one side alone breaks the app.

### Leagues and tables

A league is a property of a table: `Pool_Tables.league_type`, either
`billiards` or `ping_pong`. A match belongs to its table's league.
Routes that act on a table accept `table_id`, `league_type` (meaning
that league's table), or both - and then they must agree, or the answer
is `400`. Neither means table 1. An unknown `league_type` is `400`.

`GET /leagues` returns `{ leagues: [{ league_type, name, table_id,
table_name }] }` - how the UI finds each league's table.

### `GET /match/status?table_id=1`

Returns exactly one of (built by `manage_queue.get_player_status()`, which
also gives matchmaking a chance when the player is waiting):

| `status`                 | Meaning                              | Extra keys |
|--------------------------|--------------------------------------|------------|
| `idle`                   | Not queued, not playing              | -          |
| `queued`                 | Waiting for an opponent              | `queue_position`, `seconds_waiting`, `can_leave`, `leave_unlocks_in`, `table_id`, `league_type` |
| `waiting_for_challenger` | Won and holding the table            | `match_id`, `table_id`, `league_type` |
| `playing`                | Game in progress                     | `opponent`, `opponent_id`, `match_id`, `table_id`, `league_type` |

`league_type` is the league of the game, which can differ from the league
asked about: a player plays one game at a time, whichever league's
screen they are looking at. The UI reports the score with *this*
`league_type`, never the screen's.

`queue_position` is the player's actual place in line, 1 at the front.
(The stored column only counts up; never show it directly.)

`StatusPanel.jsx` renders one branch per value. Adding a fifth status
means adding a branch, or the panel falls through to "idle" and misleads
people. A failed status check returns `500 {message}`, never
`{"status": "idle"}` - that would offer Join to someone mid-game.

### `POST /queue/join`

Returns `{ message, status, match_started }` where `status` is `joined`
or `already_queued`. `409` means already playing. Joining always attempts
matchmaking, so an already-queued player who retries gets matched - that
is what makes a stuck queue heal itself.

### `POST /queue/leave`

`200` left, `403` still inside the wait (body carries
`leave_unlocks_in`), `404` not in the queue. The wait is enforced
server-side; the disabled button is only a courtesy.

### `POST /match/record`

Body `{ my_balls, opp_balls, match_id, league_type }`. The scores are
whole numbers in the game's own units - balls in billiards (0-8, no
tie), points in ping pong (one game to 11, won by two). They are judged
against the league of the game actually being played, under the lock
that records it; a score that doesn't fit is `400` with the reason.
`match_id` is the game the player saw; if that game has already been
recorded (their opponent reported first) the answer is `409` and nothing
is saved. Without it, a late report lands on the sender's *next* game.
`league_type` is the league the player thinks the game is in; if it's
wrong the answer is `409` (body carries the real `league_type`) and
nothing is saved. Both are optional for old clients, but the UI always
sends them. Returns `{ message, elo_change, winner_id }`. `404` no game
in progress, `409` no opponent yet.

### `POST /table/step-down`

A king with no challenger gives up the table. `200` done, `404` not
holding a table, `409` a challenger is already on (report the game).
The freed table goes to the first two in the queue.

### `GET /queue/<table_id>`

`[{ queue_position, username }]` in order, `queue_position` being the
place in line (1, 2, 3...).

### `GET /leaderboard?league_type=`

`[{ username, elo_rating, total_wins, total_losses, rank_name }]` - the
same shape for both leagues, filled from that league's columns. No
`league_type` means billiards.

### Player cards

Wherever other players are shown with their picture, the backend sends a
card (`Player.to_card`): `{ user_id, username, country_flag,
profile_picture, league_type, elo, rank_name, wins, losses }`, with the
numbers for `league_type`. The hover card reads these; hovering never
makes a request. `country_flag` is an ISO code (`"CA"`) - the client
draws the emoji. `profile_picture` is an http(s) link or null.

### `GET /table/<table_id>`

`{ table: { table_id, table_name, league_type, state, match_id, king,
challenger, king_streak } }`. `state` is `free`,
`waiting_for_challenger` or `playing`; `king` / `challenger` are player
cards or null. `404` for an unknown table. Public.

### `GET /matches/history?league_type=&table_id=&limit=`

`{ league_type, matches: [...] }`, newest first. Each entry:
`{ match_id, table_id, league_type, winner, loser, winner_score,
loser_score, elo_change, seconds_ago }`, `winner` / `loser` being player
cards. `seconds_ago` is measured by the database's clock (the same
reason as the queue timer), from when the game *finished*. `limit` is
1-50, default 20. Public.

### `GET /players/<user_id>/matches?league_type=&limit=`

As above, for one player, each entry adding `result`: `won` or `lost`.
`404` for an unknown player. Public.

### `GET /profile`, `PATCH /profile`

`GET` returns `{ profile: { user_id, username, first_name, last_name,
country_flag, profile_picture, leagues: { billiards: {elo, rank_name,
wins, losses}, ping_pong: {...} } } }`. `PATCH` takes `{ country_flag?,
profile_picture? }` (null or `""` clears one) and returns `{ message,
profile }`. A value that can't be saved is `400` with `field` naming it,
so the form can show the message beside that field; nothing is saved.
Only those two fields are editable. Both need a login.

`GET /countries` returns `{ countries: [{ code, name }] }`, sorted by
name - the picker's list, and the only codes `PATCH` accepts.

### Error response shape

Every failure returns `{ "message": "<something a person can read>" }` -
including bad tokens, unknown routes and unhandled exceptions. Exception
text never goes into a response; it goes to the server log. `api.js`
surfaces `message` directly, so the backend's wording is what people
see - unless it is long or looks technical, in which case `api.js`
substitutes a plain sentence.
