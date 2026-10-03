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
2. **Two clients, one backend.** The web app (`Frontend/`, Vite + React)
   and the mobile app (`Mobile/`, Expo + React Native) share no code at
   runtime but follow the same rules. Business rules live in the backend;
   each client's HTTP knowledge is confined to its `src/api.js`, and
   nothing else in either UI calls `fetch`. The two `api.js` files expose
   the same functions and result shapes: a contract change updates both,
   in the same commit. `src/leagues.js` and `src/flags.js` are copied
   between the two apps - a change to one is a change to both. The mobile
   app keeps its login token in Expo SecureStore, never plain storage.
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
  stuck-queue deadlock. The ready check (who is up, who has said they're
  here, who has run out of time) is part of it, not beside it;
  `confirm_here()` only records a confirmation, and callers run
  matchmaking afterwards, as they do after `join_queue()`.
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
  PyMySQL keeps it somewhere other drivers don't. Pillow redraws uploaded
  photos (`logic/pictures.py`); its wheels need no system libraries.
- Uploaded photos live in the database (`Player_Pictures`, MEDIUMBLOB on
  MySQL), never on disk: the host's disk is wiped on every deploy. In
  production the app trusts the proxy's `X-Forwarded-Proto` (ProxyFix),
  so the picture links it builds are `https://`.
- Email (password reset codes) goes out through Brevo's HTTPS API
  (`logic/mailer.py`), configured by `BREVO_API_KEY` and
  `MAIL_FROM_ADDRESS` in the host's environment. Not SMTP: Render's free
  plan blocks SMTP ports. Without them, production refuses to send and
  the app says to ask the organiser (`flask --app app set-password`).
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
view to clear a stuck table and to void a game from the app (both
by hand for now: `void-game` takes back a finished game), seasons (a
league can already be reset by hand with `flask --app app reset-league
<league>`; keeping each season's final ladder would be the next step).

**Shipped, handed to Backend 1 on 2026-09-23:** the ping pong league,
match history and player profiles. Tests: `tests/test_leagues.py`
(`LeagueRouting`, `PingPongRecording`, `PingPongScoreRules`,
`PingPongEloTests`, `LeaderboardByLeague`, `TableSnapshotRoute`),
`tests/test_match_history.py`, `tests/test_profile.py`, and the
`ensure_schema` additions in `tests/test_schema.py`.

**Shipped, handed to Backend 1 on 2026-10-03:** emails on accounts (sign-up
needs one, one account per email, sign-in by username or email, adding
or changing one), "Forgot your password?" by emailed code, the
organiser's `set-password` command, and the rating floor of 0. Tests:
`tests/test_email_accounts.py` (`SignUpWithEmail`, `SignInWithEmail`,
`ChangingYourEmail`), `tests/test_password_reset.py` (`AskingForACode`,
`ResettingThePassword`, `OrganiserSetsAPassword`),
`tests/test_elo_floor.py` (`LosingAtTheBottom`, `SayingWhatWasLost`,
`TakingBackAGameAtTheBottom`, `RatingsAlreadyBelowZero`), and the new
columns, table and index in `tests/test_schema.py`.

**Shipped, handed to Backend 1 on 2026-10-02:** `void-game`, the CLI
command that takes back a finished game played by accident
(`logic/corrections.py`) - first used on ping pong game #33. Tests:
`tests/test_corrections.py` (`VoidingAGame`, `NothingToVoid`,
`VoidGameCommand`).

**Shipped, handed to Backend 1 on 2026-10-02:** the ready check (a minute
to say you're here when your turn comes), cancelling a game when both
players agree, uploaded profile photos, public player profiles and
head-to-head records. Tests: `tests/test_ready_check.py` (`YourTurn`,
`FreeTable`, `JustJoined`, `Confirming`, `ReadyCheckRoutes`),
`tests/test_cancel_match.py` (`AskingAndAgreeing`,
`WhatHappensToTheTable`, `ChangingYourMind`, `NothingToCancel`,
`CancelRoutes`), `tests/test_pictures.py` (`Uploading`,
`PrivacyOfPhotos`, `Refusals`, `OnePictureAtATime`,
`BehindTheHostsProxy`), `tests/test_player_profiles.py`, and the new
columns and table in `tests/test_schema.py`.

**Shipped, handed to Backend 1 on 2026-10-01:** `reset-league`, the CLI
command that starts one league over (`logic/seasons.py`). Tests:
`tests/test_seasons.py` (`ResetLeague`, `ResetLeagueCommand`).

**Shipped, handed to Backend 1 on 2026-09-29:** account deletion and the
privacy policy page. Tests: `tests/test_account.py` (`DeleteAccount`,
`TokensForMissingAccounts`, `PrivacyPolicy`), and `deleted_at` in
`tests/test_schema.py`.

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
  status panel turns white). Each comes light or dark, chosen by
  `<html data-theme>` (`src/theme.js`: the player's choice, or the
  device's setting): in the dark the billiards panel keeps its purple and
  the ping pong panel turns charcoal under its purple band. A theme only
  redefines tokens, including the `--panel-*` roles the status panel
  uses; components never check which league or theme they're drawn in.
  The mobile app's `theme.js` mirrors the same four themes.
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
| `your_turn`              | Up to play: say "I'm here" in time   | `confirmed`, `seconds_left`, `opponent`, `opponent_id`, `opponent_confirmed`, `opponent_seconds_left`, `table_id`, `league_type` |
| `waiting_for_challenger` | Won and holding the table            | `match_id`, `table_id`, `league_type`, `up_next`, `up_next_seconds_left` |
| `playing`                | Game in progress                     | `opponent`, `opponent_id`, `match_id`, `table_id`, `league_type`, `cancel_requested_by` |

`league_type` is the league of the game, which can differ from the league
asked about: a player plays one game at a time, whichever league's
screen they are looking at. The UI reports the score with *this*
`league_type`, never the screen's.

`queue_position` is the player's actual place in line, 1 at the front.
(The stored column only counts up; never show it directly.)

The ready check: when a player's turn comes they have 60 seconds
(`READY_CHECK_SECONDS`) to send `POST /queue/confirm`, or they're taken
out of the queue and the next in line is up. `seconds_left` is their time
left (null once `confirmed`). The opponent is the king holding the table
(always confirmed) or the other player up at a free table, whose own
clock is `opponent_seconds_left`. A player who joined or confirmed within
the last 60 seconds is counted as here without being asked. The king's
`up_next` / `up_next_seconds_left` name who is up to challenge them and
how long they have (null when nobody is). `cancel_requested_by` is
`"you"`, `"opponent"` or null - see `POST /match/cancel`.

The status panels (`StatusPanel.jsx`, and `StatusPanel.js` in the mobile
app) render one branch per value. Adding a sixth status means adding a
branch to both, or the panels fall through to "idle" and mislead people
- which is exactly what an app built before `your_turn` shows; see
`POST /queue/join` for how it still confirms. A failed status check
returns `500 {message}`, never `{"status": "idle"}` - that would offer
Join to someone mid-game.

### `POST /queue/join`

Returns `{ message, status, match_started }` where `status` is `joined`
or `already_queued`. `409` means already playing. Joining always attempts
matchmaking, so an already-queued player who retries gets matched - that
is what makes a stuck queue heal itself. Joining again on your turn
counts as "I'm here" (how an app from before the ready check, which
shows Join instead, confirms); after the minute is up it joins again at
the back of the line.

### `POST /queue/confirm`

"I'm here". Body `{ table_id?, league_type? }` (as for joining). `200 {
message, status, match_started }`, `status` being `confirmed` or
`already_confirmed`; the game starts once everyone up has confirmed.
`409` not your turn yet, or the minute is already up (you're taken out
of the queue); `404` not in the queue.

### `POST /queue/leave`

`200` left, `403` still inside the wait (body carries
`leave_unlocks_in`), `404` not in the queue. The wait is enforced
server-side; the disabled button is only a courtesy. A player whose turn
has come may leave at once, and the next in line is up straight away.

### Ratings

No rating goes below 0 (`ELO_FLOOR`). A loss that would take a player
under it stops at it; the winner still gains the full `elo_change`. The
game keeps what the loser really lost in `loser_elo_change` (null for
games before the floor, which all lost `elo_change`). `ensure_schema()`
raises any older rating below 0 to 0, with the rank that earns.

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
sends them. Returns `{ message, elo_change, loser_elo_change, winner_id }`
- the loser's change less than `elo_change` when they stopped at 0.
`404` no game in progress, `409` no opponent yet.

### `POST /match/cancel`, `POST /match/keep`

Calling a game off takes both players. `cancel` asks - or, when the
opponent has already asked, agrees, which deletes the game: nothing is
recorded and no rating moves. `keep` takes your own request back or
turns down theirs. Body `{ match_id }` (optional for old apps), the game
the player saw. `cancel` returns `200 { message, status }` with `status`
`requested`, `already_requested` or `cancelled`; `keep` returns `kept` or
`nothing_to_keep`. `409` that game has finished (or, for `cancel`, a king
with no challenger - give up the table instead); `404` no game. After a
cancel, a king who won the last game there keeps the table; two players
who came off the queue together both go, and the table goes to the next
two.

### `POST /table/step-down`

A king with no challenger gives up the table. `200` done, `404` not
holding a table, `409` a challenger is already on (report the game).
The freed table goes to the first two in the queue.

### `GET /queue/<table_id>`

`[{ queue_position, user_id, username, called, confirmed }]` in order,
`queue_position` being the place in line (1, 2, 3...). `called` means
it's that player's turn; `confirmed` that they've said they're here.

### `GET /leaderboard?league_type=`

`[{ user_id, username, country_flag, profile_picture, elo_rating,
total_wins, total_losses, rank_name }]` - the same shape for both
leagues, filled from that league's columns. No `league_type` means
billiards. `user_id` is how a ladder row opens that player's profile.

### Player cards

Wherever other players are shown with their picture, the backend sends a
card (`Player.to_card`): `{ user_id, username, country_flag,
profile_picture, league_type, elo, rank_name, wins, losses }`, with the
numbers for `league_type`. The hover card reads these; hovering never
makes a request. `country_flag` is an ISO code (`"CA"`) - the client
draws the emoji. `profile_picture` is an http(s) link or null: either a
link the player gave, or - for a photo they uploaded - this API's own
`/players/<id>/picture?v=...`, built on the address the request came in
on.

### `GET /table/<table_id>`

`{ table: { table_id, table_name, league_type, state, match_id, king,
challenger, king_streak } }`. `state` is `free`,
`waiting_for_challenger` or `playing`; `king` / `challenger` are player
cards or null. `404` for an unknown table. Public.

### `GET /matches/history?league_type=&table_id=&limit=`

`{ league_type, matches: [...] }`, newest first. Each entry:
`{ match_id, table_id, league_type, winner, loser, winner_score,
loser_score, elo_change, loser_elo_change, seconds_ago }`, `winner` /
`loser` being player cards; `loser_elo_change` is what the loser really
lost (see *Ratings*). `seconds_ago` is measured by the database's clock (the same
reason as the queue timer), from when the game *finished*. `limit` is
1-50, default 20. Public.

### `GET /players/<user_id>/matches?league_type=&limit=&opponent_id=`

As above, for one player, each entry adding `result`: `won` or `lost`.
`opponent_id` narrows it to the games between those two (head to head;
`400` if it isn't a player id). `404` for an unknown player. Public.

### `GET /players/<user_id>`, `GET /players/<user_id>/opponents?league_type=`

A player's profile as anyone sees it: `{ player: { user_id, username,
country_flag, profile_picture, leagues: {...} } }` - never their real
name. `404` for an unknown or deleted account (the message says which).
`opponents` is their record against everyone they've played in a
league, most games first: `{ user_id, league_type, opponents: [{
opponent: card, wins, losses }] }`, wins and losses from their side.
Both public.

### `GET /players/<user_id>/picture`

An uploaded photo, as a JPEG. With the link's current `?v=` it can be
cached for good; a new photo gets a new link. `404` when the player has
none. Public.

### `GET /profile`, `PATCH /profile`

`GET` returns `{ profile: { user_id, username, first_name, last_name,
country_flag, profile_picture, picture_uploaded, leagues: { billiards:
{elo, rank_name, wins, losses}, ping_pong: {...} } } }`.
`picture_uploaded` says the picture is an uploaded photo, not a link, so
the form doesn't offer its address back as a link to edit. `email` is
the account's own (null for one made before sign-up asked for it); it is
never in any card or public profile. `PATCH` takes
`{ country_flag?, profile_picture? }` (null or `""` clears one; a new
link or none also deletes an uploaded photo) and returns `{ message,
profile }`. A value that can't be saved is `400` with `field` naming it,
so the form can show the message beside that field; nothing is saved.
Only those two fields are editable. Both need a login.

`POST /profile/email` adds or changes the email: `{ email, password? }`
-> `{ message, profile }`. Adding the first needs no password; changing
one does (`400` missing, `403` wrong - never 401 - both with `field:
"password"`). A malformed email, or one another account uses, is `400`
with `field: "email"`.

`POST /profile/picture` uploads a photo: `{ image: "<base64>" }` (a
`data:` URL is fine). The server decodes it, refuses anything that isn't
a picture or is too big (`400`, `field: "profile_picture"`; a body over
the size limit is `413`), turns it upright, crops it to a 512px square
and saves it as a new JPEG with no metadata - which is what removes the
location phones put in photos. Returns `{ message, profile }`. The apps
shrink a photo before sending it, but the server doesn't rely on that.

`GET /countries` returns `{ countries: [{ code, name }] }`, sorted by
name - the picker's list, and the only codes `PATCH` accepts.

### `POST /profile/delete`

Deletes the signed-in player's account. Body `{ password }` - asked for
again. `200 { message }` deleted; `400` no password and `403` wrong
password, both with `field: "password"` (a 403, never a 401: to the apps
a 401 means "session ended"); `409` a game in progress - report it first.

Deleting wipes the Players row's personal details (username becomes a
random placeholder, names, email, flag, picture - an uploaded photo and
any reset code are deleted outright - password) and sets `deleted_at`; the row stays so other players' history keeps working,
shown as "Deleted player" (`Player.display_name`). The player leaves
every queue, gives up a held table and drops off the ladder. Both app
stores require this, in the app, for any app with sign-up.

A login token for a deleted - or never-existing - account is refused on
every signed-in route with `401` (`token_in_blocklist_loader` in
app.py), not honoured until it expires.

### Signing up and signing in

`POST /register` takes `{ username, first_name, last_name, email,
password }`. The email is required, kept lowercased, and one account per
email - what stops a player who forgot their password making a second
account. Usernames can't contain `@`. `201 { message }`; a refusal is
`400 { message, field }` naming the field, and a body with no `email` at
all (an app from before) says to update the app.

`POST /login` takes `{ username, password }`, where `username` may be
the email: anything with an `@` is looked up as an email first, then as
a username (some older accounts use an email address as their username). `200 { message, access_token, user_id,
username, email }`; `email` is null for an account from before sign-up
asked for one, and the apps then ask the player to add it (`POST
/profile/email`) before anything else. `401` for wrong details.

### `POST /password/forgot`, `POST /password/reset`

Forgot your password. `forgot` takes `{ email }` and emails the account
a 6-digit code (`logic/password_reset.py`); it answers `200 { message }`
whether or not an account has that email, so it can't be used to find
out who plays. A new code at most once a minute; it works for 15
minutes and 5 tries. `503` when email isn't set up on the server, or
can't be sent just then. `reset` takes `{ email, code, password }`:
`200` answers exactly like `/login` - the player is signed in - and a
refusal is `400` with `field` `code` (wrong, expired, too many tries, or
none asked for) or `password`.

### `GET /privacy`

The privacy policy as an HTML page (`logic/privacy.py`), linked from both
apps and from the store listings. It must describe what the app actually
stores: a new kind of data collected means an update here. The contact
address comes from `PRIVACY_CONTACT_EMAIL` in the host's environment.

### Error response shape

Every failure returns `{ "message": "<something a person can read>" }` -
including bad tokens, unknown routes and unhandled exceptions. Exception
text never goes into a response; it goes to the server log. `api.js`
surfaces `message` directly, so the backend's wording is what people
see - unless it is long or looks technical, in which case `api.js`
substitutes a plain sentence.
