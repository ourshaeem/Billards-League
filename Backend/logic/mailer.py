"""
Sending email - for now only password reset codes.

Through Brevo's HTTPS API, not SMTP: Render's free plan blocks outgoing
SMTP (ports 25, 465 and 587) since September 2025. Brevo's free plan
sends 300 emails a day. Configured from the environment:

  BREVO_API_KEY      an API key (Brevo: Settings > SMTP & API > API keys)
  MAIL_FROM_ADDRESS  the sender, verified in Brevo (Senders)
  MAIL_FROM_NAME     the name shown; "Billiards & Ping Pong League" if unset

Without them, in local development the email is written to the log
instead, so the reset flow can be tried end to end; in production,
sending raises MailNotConfigured, which the route turns into a plain
"ask the organiser" message.

Uses the standard library rather than a new dependency: one POST.
"""
import json
import logging
import os
import urllib.error
import urllib.request

from database import is_production

log = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_FROM_NAME = "Billiards & Ping Pong League"
SEND_TIMEOUT_SECONDS = 10


class MailNotConfigured(RuntimeError):
    """No email service is set up on this server."""


class MailFailed(RuntimeError):
    """The email service refused the email or couldn't be reached."""


def mail_configured():
    """True if this server can send email (or, locally, pretend to)."""
    return bool(_setting("BREVO_API_KEY") and _setting("MAIL_FROM_ADDRESS")) or not is_production()


def _setting(name):
    return os.environ.get(name, "").strip()


def send_email(to_address, subject, text):
    """
    Send a plain-text email. Raises MailNotConfigured or MailFailed; the
    error never includes the API key.
    """
    api_key, sender = _setting("BREVO_API_KEY"), _setting("MAIL_FROM_ADDRESS")
    if not (api_key and sender):
        if is_production():
            raise MailNotConfigured("BREVO_API_KEY and MAIL_FROM_ADDRESS aren't set")
        log.warning("email isn't set up, so here it is instead:\nTo: %s\nSubject: %s\n\n%s",
                    to_address, subject, text)
        return

    payload = {
        "sender": {"email": sender, "name": _setting("MAIL_FROM_NAME") or DEFAULT_FROM_NAME},
        "to": [{"email": to_address}],
        "subject": subject,
        "textContent": text,
    }
    request = urllib.request.Request(
        BREVO_SEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS) as response:
            response.read()
    except urllib.error.HTTPError as e:
        detail = e.read(500).decode("utf-8", errors="replace")
        log.error("Brevo refused an email (%s): %s", e.code, detail)
        raise MailFailed(f"the email service answered {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.error("couldn't reach Brevo: %s", e)
        raise MailFailed("the email service couldn't be reached") from None
