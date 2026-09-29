"""
The privacy policy, served as a web page at GET /privacy.

Both app stores ask for a public link to one, and the app links to it
from the Profile screen. It describes what this app actually does - if
the app starts collecting something new, this page has to say so.

The contact address comes from PRIVACY_CONTACT_EMAIL (set it in Render),
so a personal address never has to be committed to the repository.
"""
import os
from html import escape

LAST_UPDATED = "29 September 2026"


def privacy_policy_html():
    contact = os.environ.get("PRIVACY_CONTACT_EMAIL", "").strip()
    if contact:
        contact_line = (
            f'Email <a href="mailto:{escape(contact)}">{escape(contact)}</a>.'
        )
        ask_by_email = (
            f' If you can\'t open the app, email <a href="mailto:{escape(contact)}">'
            f"{escape(contact)}</a> from any address, with your username, and "
            "we'll delete the account for you."
        )
    else:
        contact_line = "Ask the person who runs your league."
        ask_by_email = (
            " If you can't open the app, ask the person who runs your league to "
            "delete it for you."
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy policy - Billiards &amp; Ping Pong League</title>
<style>
  :root {{ --purple: #5b21b6; --text: #1b1a22; --muted: #676775; --line: #e3e3e9; }}
  body {{ margin: 0; font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
         color: var(--text); background: #fff; }}
  main {{ max-width: 680px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 1.8rem; line-height: 1.2; color: #2e1065; margin: 0 0 4px; }}
  h2 {{ font-size: 1.15rem; margin: 32px 0 8px; padding-top: 16px; border-top: 1px solid var(--line); }}
  p, li {{ margin: 0 0 10px; }}
  .updated {{ color: var(--muted); margin-bottom: 24px; }}
  a {{ color: var(--purple); }}
</style>
</head>
<body>
<main>
<h1>Privacy policy</h1>
<p class="updated">Billiards &amp; Ping Pong League. Last updated {LAST_UPDATED}.</p>

<p>Billiards &amp; Ping Pong League is a small community app for running the queues,
scores and ladders at our pool and ping pong tables. This page explains what it
stores about you, who can see it, and how to delete it.</p>

<h2>What we store</h2>
<ul>
  <li><strong>Your account:</strong> your username, first and last name, and your
  password. The password is stored only as a one-way hash (bcrypt), so nobody -
  including us - can read it.</li>
  <li><strong>Your profile, if you add one:</strong> a country flag and a link to a
  profile picture.</li>
  <li><strong>Your league activity:</strong> when you join or leave a queue, the games
  you play and their scores, and your ratings, ranks, wins and losses.</li>
  <li><strong>Server logs:</strong> the service that hosts our server keeps standard
  logs of requests (such as IP address and time) for security and troubleshooting.</li>
</ul>
<p>We don't collect your location, contacts, photos or device identifiers, and the
app has no advertising and no analytics or tracking.</p>

<h2>Who can see it</h2>
<p>Other players can see your username, flag and profile picture, your ranks,
ratings and win-loss records, your place in a queue, and the games you've played.
That is how the league works. Your first and last name and your password are never
shown to other players.</p>
<p>A profile picture is loaded from the web address you give, so whoever hosts
that image can see when it's viewed.</p>

<h2>How we use it</h2>
<p>Only to run the league: signing you in, queueing and matching players,
recording scores and keeping the ladders. We don't sell your information or share
it with advertisers.</p>

<h2>Where it's kept</h2>
<p>Our database is hosted by Amazon Web Services and our server by Render, both in
the United States. Connections between the app, the server and the database are
encrypted.</p>

<h2>How long we keep it</h2>
<p>Until you delete your account. Server logs are kept for a limited time by our
hosting provider and then deleted.</p>

<h2>Deleting your account</h2>
<p>In the app, open <strong>Profile</strong>, choose <strong>Delete account</strong>
and enter your password. This removes your username, name, flag, picture and
password straight away, takes you out of every queue and off the ladders, and
signs you out everywhere. Games you played stay in other players' history, shown
as "Deleted player" with nothing that identifies you. It can't be undone.{ask_by_email}</p>

<h2>Children</h2>
<p>The app isn't meant for children under 13, and we don't knowingly collect
information from them.</p>

<h2>Changes</h2>
<p>If what we store or how we use it changes, we'll update this page and the date
at the top.</p>

<h2>Contact</h2>
<p>Questions about your information? {contact_line}</p>
</main>
</body>
</html>
"""
