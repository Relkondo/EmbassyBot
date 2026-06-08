USERNAME = "your-login-email"
PASSWORD = "your-login-password"

# A fresh CAPTCHA token is requested through CapSolver on each login attempt.
CAPSOLVER_API_KEY = ""
CAPTCHA_URL = "https://www.usvisaappt.com/visaapplicantui"
CAPTCHA_KEY = ""
ANCHOR_BASE_64 = ""
RELOAD_BASE_64 = ""

# Updated automatically after login. Used until it is within five minutes of
# expiry, then the bot performs a full login and stores the new token.
AUTHORIZATION_TOKEN = ""

# Optional selector. Leave empty to use the most recently created application.
APPLICATION_ID = ""

# Leave empty to disable automatic booking. When set, slots strictly before
# this date are automatically booked after GET_TIME returns a slotId.
BOOKING_DATE_LIMIT = ""

# Stores announced appointment datetimes so service restarts do not re-alert them.
STATE_FILE = "embassy_bot_state.json"

BASE_INTERVAL_SECONDS = 180
JITTER_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 30

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
