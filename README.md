# EmbassyBot

Python bot for polling US visa appointment slots after logging in with the
site's browser-compatible encrypted authorization header.

The bot expects a manually supplied `CAPTCHA_TOKEN` in `config.py`. It does not
solve or bypass CAPTCHA challenges itself.

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

- `USERNAME`, `PASSWORD`, `CAPTCHA_TOKEN`
- `AUTHORIZATION_TOKEN`, `REFRESH_TOKEN`
- `APPLICANT_ID`, `APPLICATION_ID`, `POST_USER_ID`
- `FROM_DATE`, `TO_DATE`, `CURRENT_APPOINTMENT_DATE`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

`CURRENT_APPOINTMENT_DATE` is treated as exclusive. A returned slot on any date
before that value triggers a Telegram notification.

If `AUTHORIZATION_TOKEN` is set, the bot tries the slot request first and skips
login. If that request returns `401` or `403`, it logs in once and rewrites
`AUTHORIZATION_TOKEN` and `REFRESH_TOKEN` in `config.py`.

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
