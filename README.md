# Billiards & Ping Pong League

Queue up for the pool table or the ping pong table, report your score,
and track each league's ladder.

After signing in, players pick a league for the session. Both leagues run
the same king-of-the-hill queue: winner stays on, next in line plays
them. When it's your turn you have a minute to say you're here, or the
next person is up; and a game both players agree to call off is cancelled
with nothing recorded. Each league has its own ratings, ranks, ladder,
match history and colours (billiards: purple, white, gray; ping pong:
white, purple, gray), each in light and dark. Tap any player to see their
profile, their games and their record against you.

Stack: **MySQL + Python/Flask + React (Vite)**. Kept deliberately plain so
the app can be ported to React Native later.

---

## Running it

### Backend

```bash
cd Backend
pip install -r requirements.txt

cp .env.example .env      # then edit .env with your database password

python app.py             # http://localhost:5000
```

There is no SQL to run by hand. On startup `ensure_schema()` (in
`Backend/database.py`) builds an empty database or brings an existing one
up to date, and `check_schema()` then reports anything still missing in
plain words. `ensure_schema()` only ever adds - no column or table is
dropped - and it is safe to run on every start. It:

- creates any table the models map that doesn't exist yet (on a brand-new
  database, all of them), and fills an empty `Ranks` table with the
  league's tiers (Unranked 0, Bronze 200, Silver 500, Gold 800,
  Platinum 1200),
- adds any missing column the app has gained since the database was
  built (listed in `ADDED_COLUMNS`): `Queue.joined_at` (the leave-queue
  timer), `Pool_Tables.league_type`, the ping pong ratings and records
  on `Players`, and each player's `country_flag` and `profile_picture`,
- adds "Table 1" to `Pool_Tables` if missing (joins fail without it),
- adds a "Ping Pong Table" if no table belongs to the ping pong league,
- gives players who have never played ping pong the starting ping pong
  rank, as registration now does,
- converts match rows written by the original code, which kept the two
  seats in `winner_id`/`loser_id`, into `king_id`/`challenger_id`,
- removes duplicate queue entries, then adds the indexes the models
  declare, including a unique one that stops a double-tapped Join
  queueing someone twice.

Each step prints a `[schema]` line when it changes something.

`Backend/.env` holds your local database password (`DB_PASSWORD`); no
password is written in the code. Git ignores the file. Without it the app
stops at startup and says what to do. The live server doesn't use it -
its settings are Render's environment variables.

### Frontend

```bash
cd Frontend
npm install
npm run dev               # http://localhost:5173
```

To point the UI at a different backend (for example, testing from a phone
on the same wifi, where `localhost` means the phone itself), create
`Frontend/.env`:

```
VITE_API_BASE=http://192.168.1.50:5000
```

### Deploying

The backend ships as a Docker image (`Backend/Dockerfile`) served by
gunicorn, for any host that runs containers - Render, Railway, AWS. It
reads everything from environment variables; `Backend/.env.example`
lists them. Two are required:

- `DATABASE_URL` - e.g. an AWS RDS MySQL endpoint:
  `mysql+pymysql://USER:PASSWORD@ENDPOINT:3306/DB_NAME?ssl_ca=/app/certs/rds-global-bundle.pem`
  (`ssl_ca` encrypts the connection, using Amazon's certificates baked
  into the image).
- `JWT_SECRET_KEY` - a long random string.

On each start gunicorn first runs `flask prepare-db` (which runs
`ensure_schema()`) as a separate process, before any worker takes a
request, so a fresh database needs no setup. You can also run it by hand
from `Backend/`: `flask --app app prepare-db`.
If the database can't be reached, or `JWT_SECRET_KEY` is missing, the
start fails with the reason in the host's log rather than running
broken. Health check path: `/health`.

On Render, `render.yaml` at the repository root describes the whole
service: New -> Blueprint, pick this repo, paste `DATABASE_URL` when
asked. Render generates `JWT_SECRET_KEY` itself.

To try the image locally:

```bash
docker build -t league-api Backend
docker run --rm -p 5000:5000 --env-file Backend/.env league-api
```

(`--env-file` passes your settings in; inside a container, a database on
your own machine is `host.docker.internal`, not `127.0.0.1`.)

The privacy policy the app stores ask for is served at `/privacy` on the
backend. Set `PRIVACY_CONTACT_EMAIL` on the host so it shows a contact
address. Players can delete their accounts from Profile in either app
(`POST /profile/delete`), which both stores require.

CORS currently allows any origin (`CORS_ORIGINS=*`), for the React Native
work. Sign-in uses the Authorization header, not cookies, so this doesn't
let other sites act as a player; narrow it once the web frontend has an
address.

### Mobile app

`Mobile/` is the iOS and Android app, built with Expo (SDK 57) and React
Native, talking to the live backend on Render. Install **Expo Go** from
the App Store or Play Store on your phone, then:

```bash
cd Mobile
npm install
npx expo start            # scan the QR code with your phone's camera (iOS)
                          # or from inside Expo Go (Android)
```

To point it at a backend on your own computer instead, see
`Mobile/.env.example`, and restart with `npx expo start --clear` - Expo
caches the address. Sign-in tokens are kept in Expo SecureStore (the iOS
Keychain / Android Keystore), not plain storage.

Choosing a photo uses `expo-image-picker` and `expo-image-manipulator`,
and the turn buzz `expo-haptics`. They're native code, so an app built
before them (the APK up to version 3) needs replacing with a new build
(`npx eas-cli build --platform android --profile preview`). Expo Go
already has them. There are no push notifications: a player whose turn
is coming needs the app open to see it.

`npx expo start --web` runs the same app in a browser, which is handy for
a quick look but isn't what ships to phones.

### Starting a league over (a new season)

Puts every player's rating, record and rank in one league back to a new
player's, keeps the finished games in the history, and leaves the other
league alone. Everyone's old numbers are saved to `Backend/backups/`
(gitignored) first. From `Backend/`, against the live database:

```bash
DATABASE_URL="<the live DATABASE_URL, with ssl_ca pointing at a downloaded RDS bundle>" \
  flask --app app reset-league ping_pong      # or billiards
```

It prints which database and how many players before asking to confirm.

### Emailing password reset codes

Signing up takes an email, one account per email, so a player who forgets
their password resets it ("Forgot your password?" on the sign-in screen)
instead of making a second account. The code goes out through
[Brevo](https://www.brevo.com) (free for 300 emails a day), over HTTPS:
Render's free plan blocks the usual SMTP ports. To switch it on:

1. Sign up at brevo.com. Under **Senders**, add the address the codes
   should come from; Brevo emails it a confirmation link.
2. Under **SMTP & API > API keys**, generate a key.
3. In Render, add `BREVO_API_KEY` (the key) and `MAIL_FROM_ADDRESS` (the
   sender) to the service's environment variables.

Without a domain of your own, Brevo sends from a stand-in
`@brevosend.com` address that may land in spam, which the app tells
people to check. Until it's set up, "Forgot your password?" tells
players to ask the organiser, who can set a new one from `Backend/`:

```bash
DATABASE_URL="<the live DATABASE_URL>" flask --app app set-password <username-or-email>
```

### Taking back a game played by accident

Removes one finished game from the history and undoes exactly what it
did: the winner gives back the points it gave them, the loser gets back
what it cost them, and each loses it from their record. Games since stay
as they were. Find the game's `match_id` in `GET /matches/history`, then
from `Backend/`, against the live database (as for a reset):

```bash
DATABASE_URL="<the live DATABASE_URL>" flask --app app void-game 33
```

It shows the game and both players' numbers before and after, asks
first, and saves a backup to `Backend/backups/`.

### The organiser's controls

An admin sees a **Remove** button beside every player at the table and
in the queue, in the web app and the phone app, for someone who has
walked off. Taking a player out of the queue ignores the usual wait;
taking one off the table gives it to the next in line, or - mid-game -
calls the game off with nothing recorded, and their opponent keeps the
table. The app asks first. To make someone an admin (or, with `--off`,
stop them being one), from `Backend/`, against the live database:

```bash
DATABASE_URL="<the live DATABASE_URL>" flask --app app set-admin Shaeem
```

The server checks on every request, so the buttons appear the next time
the app loads that player's profile (reopening the phone app, or
changing screen on the web).

### Deleting duplicate or joke accounts

Deletes accounts exactly as if each player had deleted their own: their
details are wiped, they leave every queue, a table they hold is given
up, and they drop off both ladders. Games they played stay in everyone
else's history as "Deleted player", and nobody's points change - to
undo one of those games as well, use `void-game`. From `Backend/`,
against the live database (as for a reset), naming each account by its
exact username or its email:

```bash
DATABASE_URL="<the live DATABASE_URL>" flask --app app delete-player Parceval "someone@example.com"
```

It lists each account, how many games it played and whether it's at a
table, and asks first. A name that matches nobody stops the whole run
before anything is deleted, and a player in the middle of a game is
skipped. The list - no names, emails or passwords - is saved to
`Backend/backups/`. A deleted account can't be brought back.

### Tests

```bash
cd Backend
python -m unittest discover -s tests -t .
```

These run the real ORM against an in-memory SQLite database - no mocks,
no SQL translation shim. Mocks agree with whatever you ask them, which is
how the original queue bug survived having a test file at all.

---

## What was wrong, and what changed

### Round 2: "I can't join the queue on my second account"

**What people saw.** Pressing Join on the second account popped up a box
full of SQL that couldn't be closed, and the player never joined.

**Cause.** The previous rewrite described a `Matches` table with
`player_one_id`/`player_two_id` columns. The real database has never had
them - its columns are `king_id`, `challenger_id`, `winner_id`,
`loser_id`, `king_balls`, `challenger_balls`. The migration that was
meant to bridge the two targeted a different layout again, so it was
never going to help. Every query touching a match failed, and the join
route put the raw exception text into its response. On top of that, the
game already in the database was stored the original way (seats in
`winner_id`/`loser_id`), so one player was holding the table in a way
the new code couldn't see.

**Fix.**
- The models now map onto the columns that exist. `check_schema()`
  compares the models against the database itself, so this kind of
  drift is reported at startup instead of in a player's face.
- `ensure_schema()` converts old match rows on startup (see above).
- No response carries exception text any more. Failures are logged in
  the terminal and the player gets one readable sentence. `api.js` also
  refuses to display anything long or technical-looking, as a second lock.
- Toasts can always be closed: the close button stays in view, Escape
  closes them all, errors fade after 8 seconds (held while hovered), long
  text scrolls inside a capped box, and at most three show at once.
- A status check gives matchmaking a chance whenever the player is
  waiting, so a stuck queue heals on the next poll.

### Found by play-testing

The app was then played by scripted accounts against a copy of the
database, with 12 players doing up to 8 things at the same instant, and
by two real browser sessions. That turned up and fixed:

- **A late second report recorded a game that hadn't happened.** When
  both players reported, the winner's report landed on their *next*
  game, against whoever had just come off the queue. Reports now carry
  `match_id`, and a report for a game already recorded is refused (409).
- **Two reports at the same instant could both land.** The match row is
  now locked while a result is recorded.
- **Stale reads under load.** A locked read could be answered from
  SQLAlchemy's cache of a row loaded earlier in the request, so a king
  could look challenger-less and have a just-matched challenger
  overwritten. Every locked read now refreshes (`populate_existing`), and
  anything that changes who is at a table first locks that table's row.
- **Double-tapping Join** could queue a player twice, and could then
  match them against themselves. A unique index prevents it, and
  matchmaking also skips any queue row for someone already playing.
- **MySQL deadlocks** when taps collide are now retried instead of
  becoming a 500.
- **The winner of the last game held the table forever.** There was no
  way to leave; the next day's first joiner was matched against someone
  who'd gone home. The king can now give up the table.
- **"You're number 253 in line"** to someone eleventh of eleven: the
  stored queue position only ever counts up. The API now reports the
  actual place in line.
- **Ratings of 0 were treated as unrated**, so a new player's first win
  jumped them to 1216. New players now start at 0, matching the
  database default and the `Ranks` table (whose lowest tier is 0), and
  get their starting rank when they register.
- **The 30-second leave wait wasn't enforced in tests.** SQLite has no
  `TIMESTAMPDIFF`, and the fallback let everyone leave at once; four
  tests had been failing because of it.
- Bodies that were valid JSON but not an object, numbers where text was
  expected, over-long usernames and names (the columns hold 50), and
  passwords over 72 bytes (bcrypt's limit) were all 500s or vague
  messages; each now gets a specific 400. Scores like `8.5` were quietly
  rounded down; they're refused now.
- A wrong password no longer reads as "session ended", and the status
  panel no longer flashes a Join button before the first status arrives.

### Round 1: "already in the queue", but no match ever starts: "already in the queue", but no match ever starts

**Cause.** `/queue/join` in `app.py` had its own private copy of the
matchmaking logic, and that copy only knew one scenario: an empty table
with two people waiting. But the app also runs king-of-the-hill - the
winner stays at the table waiting for a challenger - and *that* pairing
logic only existed in `record_match.py`, which the join route never
called.

So the moment anyone won a game, the table had a "king" sitting in the
`Matches` table with no opponent. Everyone who joined after that was
genuinely added to the queue (hence the message), and nothing ever paired
them with the king. The other player looked absent because kings aren't
in the `Queue` table at all - they're in `Matches`.

**Fix.** There is now exactly one matchmaking implementation,
`manage_queue.attempt_matchmaking()`, which handles both scenarios. Both
the join route and the end-of-match handler call it. Joining always
attempts matchmaking, so anyone already stuck in a queue from before this
fix gets matched simply by tapping Join again - no manual database
cleanup needed.

**Guarded by:** `test_king_waiting_gets_matched_when_someone_joins` and
`test_retrying_a_stuck_join_self_heals`. Both were checked against the
old code first and do fail against it, so they genuinely catch the bug
rather than just passing.

### The leave-queue button

New `POST /queue/leave`, plus a button in the status panel. It unlocks
after 30 seconds of waiting with no match, so an accidental join is
escapable but nobody can dodge a match that's about to start. Change
`LEAVE_UNLOCK_SECONDS` in `Backend/logic/manage_queue.py` to adjust.

The wait is enforced **server-side**. The disabled button is a courtesy;
posting directly to the endpoint is also refused, and there's a test for
exactly that.

### Other bugs found and fixed along the way

**A timezone bug that would only have appeared on your machine.** The
first version of the leave timer compared MySQL's `CURRENT_TIMESTAMP`
against Python's `datetime.now()`. Those are different clocks in
different timezones. With MySQL on UTC and the app running in New York,
`joined_at` reads about four hours into the future, the remaining wait
goes negative, and the leave button never unlocks. Elapsed time is now
computed inside the database with `TIMESTAMPDIFF`, so both values come
from one clock.

- **`POST /queue/join` returned 415** when the request had no
  `Content-Type: application/json` header. Every route now reads its body
  safely.
- **Winner and loser could be stored backwards.** The two seats in a new
  match are assigned arbitrarily from queue order, so finishing a match
  has to set the columns explicitly rather than rely on where people
  started.
- **Recording a score against a king with no opponent** wrote a null
  opponent into the row. Now a clean 409.
- **Login could crash** with `AttributeError` when MySQL returned the
  password hash as `bytes` rather than `str`.
- **Registration said "Registration failed"** for every cause. It now
  says which one - taken username, password too short, and so on.
- **Flat 20-point ELO** replaced with real ELO, so beating someone well
  above you is worth more than beating someone below you. Still
  zero-sum.
- **`/debug/start-match` had no login requirement** and could force-start
  matches for anyone who could reach the server. It now only exists when
  `ENABLE_DEBUG_ROUTES=1`.
- **Polling restarted on every queue change**, tearing down and
  rebuilding the timer whenever anyone joined or left. It now depends
  only on who's signed in, and aborts cleanly on unmount.
- **A refresh logged you out** even with a valid token. The session is
  restored on load.

### Frontend

- All HTTP moved into `Frontend/src/api.js`, which normalises every
  response and sorts failures into network / auth / rejected / server.
  A dropped connection no longer looks like a wrong password.
- `alert()` is gone. Messages appear as toasts; validation errors appear
  next to the field they concern.
- The UI understands all four player states. Previously anyone holding
  the table looked "idle" and was shown a Join button that then failed
  with "already playing".
- An offline banner appears when polling can't reach the server, instead
  of the numbers just quietly going stale.
- Redesigned in purple and white, with gray as the secondary colour; the
  status panel is the one solid purple block. Responsive to phone width,
  visible keyboard focus, and `prefers-reduced-motion` respected.

---

## Security note, worth doing once

The MySQL password was committed in `Backend/database.py` and the JWT
signing key in `Backend/app.py`. Both are in this repository's git
history, and the repository is on GitHub.

Moving them into `.env` stops *new* commits leaking them, but does not
remove them from past commits. Two things worth doing:

1. Change the MySQL password, and put the new one only in `Backend/.env`.
2. Set a new `JWT_SECRET_KEY` in `Backend/.env`. Everyone gets signed out
   once, which is the point - old tokens stop working.

---

## Project layout

```
Backend/
  app.py                    HTTP routes (app factory: create_app)
  models.py                 SQLAlchemy models + API serializers
  database.py               connection URI, ensure_schema, check_schema,
                            prepare_database, deadlock retry
  Dockerfile                production image (gunicorn, non-root user)
  gunicorn.conf.py          workers, port, and the one-per-start schema run
  logic/
    manage_queue.py         joining, leaving, matchmaking (single source of
                            truth) with its one-minute ready check, player
                            status, giving up the table
    record_match.py         reporting results, score rules and ELO for
                            both leagues, king handoff
    cancel_match.py         calling a game off when both players agree
    tables.py               which league a table is in, and who's at it
    match_history.py        finished games, per league, per player and
                            head to head; records against each opponent
    profile.py              reading profiles, changing flag and picture
    pictures.py             uploaded photos: checked, cropped, shrunk and
                            stripped of location data, kept in the database
    countries.py            the country list flags are picked from
    auth.py                 registration (email required, one account per
                            email) and login (username or email)
    password_reset.py       forgot your password: an emailed code
    mailer.py               sending email through Brevo's HTTPS API
    leaderboard.py          top 50, per league
  tests/                    ORM tests against in-memory SQLite

Frontend/
  index.html                fonts, title
  src/
    api.js                  ALL backend calls (the React Native port starts here)
    App.jsx                 session, league choice, polling, actions
    leagues.js              league names, score rules, quick-score buttons
    flags.js                country code -> flag emoji
    theme.js                light / dark choice, remembered on the device
    photo.js                cropping and shrinking a photo before upload
    openPlayer.js           how any name opens that player's profile
    index.css               design tokens (both league themes, light and
                            dark) and styles
    components/
      StatusPanel.jsx       the five player states: join, I'm here, leave,
                            report or cancel a game, give up the table
      LeagueSelect.jsx      choosing billiards or ping pong after sign-in
      ActiveTable.jsx       who is at the table right now
      MatchHistory.jsx      recent games, everyone's or yours
      PlayerProfile.jsx     another player: standings, record against
                            everyone and against you, their games
      ProfileSettings.jsx   flag, photo or picture link, light / dark,
                            standing in both leagues
      Player.jsx            avatar, name + flag, hover card (rank, rating)
      Panels.jsx            queue list, ladder
      AuthScreens.jsx       sign in, register
      Feedback.jsx          toasts, offline banner, field errors

Mobile/                     the Expo / React Native app
  App.js                    fonts and providers, then the navigator
  src/
    api.js                  ALL backend calls - the twin of Frontend/src/api.js
    config.js               server address (live Render by default), polling pace
    storage.js              session and light / dark choice in SecureStore
    theme.js                design tokens, both league themes, light and dark
    photo.js                picking, cropping and shrinking a photo
    leagues.js, flags.js    copied from Frontend/src - keep in step
    state/                  appearance, session, league, live queue/table
                            data and actions, toasts
    navigation/             sign-in stack -> league picker -> tabs, player
                            profiles over the tabs
    screens/                sign in, register, league picker, Play, Games,
                            Ladder, Profile, a player's profile
    components/             status panel, turn banner, table and queue
                            cards, game rows, player chip, flag picker,
                            buttons and fields

AGENTS.md                   the six roles and the contracts between them
render.yaml                 Render Blueprint: deploys Backend/ as a Docker service
```

## How the two leagues work

A league is a property of a table (`Pool_Tables.league_type`). Queues
and matches were already keyed on `table_id`, so matchmaking - still
exactly one implementation, `attempt_matchmaking()` - serves both
leagues without knowing either exists. A match's league is its table's.

- **Billiards** ratings are the original `elo_rating` / `rank_id`
  columns. The model also calls them `billiards_elo` /
  `billiards_rank_id`; those are aliases, not second copies.
- **Ping pong** has its own `ping_pong_elo`, `ping_pong_rank_id`,
  `ping_pong_wins`, `ping_pong_losses`. Both leagues share the `Ranks`
  tiers.
- **Scores** are judged by the rules of the game's own league, whatever
  league the request claims: billiards 0-8, no tie; ping pong one game to
  11, won by two (11-9, 12-10). A report sent with the wrong
  `league_type` is refused (409) and nothing is saved.
- **Nobody goes below 0 points.** A loss that would take a player under
  0 stops at 0; the winner still gains the full amount. The game
  remembers what the loser really lost (`loser_elo_change`), which the
  history shows - "+16 points" when the loser had nothing to lose.
- **Ping pong ELO** uses the standard Elo expectation with tiered
  K-factors - 40 for a player's first 10 games, 24 after that, 16 from a
  rating of 1200 - averaged between the two players so the ladder stays
  zero-sum. A lopsided game moves up to 50% more than a close one (11-0
  vs 11-9 or a deuce game). Billiards keeps its flat K of 32.

## Taking turns, and calling a game off

- **The ready check.** When a player's turn comes - a king is waiting for
  a challenger, or the table is free and they're one of the first two in
  line - they have a minute to tap "I'm here". If they don't, they're
  taken out of the queue and the next person is up. At a free table both
  players must say they're here; the game starts once they have.
  Someone who joined (or said they were here) within the last minute
  isn't asked again, so joining a table with room starts at once. The
  minute is timed by the database's clock, and enforced by the server
  whichever app is asking. It's part of `attempt_matchmaking()` - still
  the one place matchmaking happens.
- **Cancelling a game.** Either player can ask to cancel; nothing happens
  until the other agrees, and either can take it back. A cancelled game
  records nothing and moves nobody's rating. If the first player was
  holding the table (they won the last game there), they keep it and the
  next in line is up; otherwise the table goes to the next two.

## Next steps

`AGENTS.md` lists candidates. With two leagues on two tables, **more
tables per league** is mostly a frontend job now: the backend already
accepts any `table_id`, and the UI uses each league's first table.
