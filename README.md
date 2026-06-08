# EmbassyBot

Python bot for polling US visa appointment slots after logging in with the
site's browser-compatible encrypted authorization header.

On each login attempt, the bot requests a fresh CAPTCHA token through CapSolver.

## Local Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m embassy_bot.main
```

For repeated one-shot testing, run:

```bash
python -m embassy_bot.main --once
```

Fill `config.py` before running. The most important fields are:

- `USERNAME`, `PASSWORD`
- `CAPSOLVER_API_KEY`, `CAPTCHA_URL`, `CAPTCHA_KEY`
- `ANCHOR_BASE_64`, `RELOAD_BASE_64` if CapSolver needs anchor/reload payloads
- `AUTHORIZATION_TOKEN`
- `APPLICATION_ID` as an optional selector if multiple applications exist
- `BOOKING_DATE_LIMIT`
- `STATE_FILE`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

After authentication, the bot calls GET_LANDING_PAGE_DETAILS and extracts the
current appointment, applicant, visa, post, and alert date values from the
selected application. If `APPLICATION_ID` is empty, the most recently created
application is selected.
In long-running polling mode, this appointment context is loaded once and
reused across polls. After a successful booking, it is cleared so the next poll
reloads the updated current appointment.

The current appointment date from GET_LANDING_PAGE_DETAILS is treated as the
alert date limit. If FIRST_MONTH returns a date on or before that value, the bot
requests that month of SLOTS. When the earliest SLOTS date is also on or before
the alert limit, the bot requests GET_TIME for that date and sends the returned
appointment start times to Telegram.

`BOOKING_DATE_LIMIT` is optional. Leave it empty to disable automatic booking.
When set, any GET_TIME slot strictly before that date is booked with the
appointmentId from GET_LANDING_PAGE_DETAILS, and the Telegram message reports
the booked time.

`STATE_FILE` stores appointment datetimes that were already announced, so a
service restart does not repeat availability messages. Relative paths are
resolved next to `config.py`. It is written when the long-running process exits.

If `AUTHORIZATION_TOKEN` is set, the bot uses it until it is within five minutes
of expiry, which is roughly 55 minutes after login for the current site tokens.
At that point it performs a full login and CAPTCHA again. If an authenticated
call returns `401` or `403`, the bot also falls back to full login and retries
that call once. Fresh `AUTHORIZATION_TOKEN` values are persisted back to
`config.py`.

## EC2 / systemd

Recommended deployment path:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin embassybot
sudo mkdir -p /opt/EmbassyBot
sudo chown -R embassybot:embassybot /opt/EmbassyBot
```

Place the project in `/opt/EmbassyBot`, create the virtual environment, install
dependencies, and fill `/opt/EmbassyBot/config.py`. Then install the service:

```bash
sudo cp deploy/embassy-bot.service /etc/systemd/system/embassy-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now embassy-bot
```

Useful service commands:

```bash
sudo systemctl status embassy-bot
sudo journalctl -u embassy-bot -f
sudo systemctl restart embassy-bot
```

## Tests

```bash
python -m unittest discover -s tests
```
