USERNAME = "your-login-email"
PASSWORD = "your-login-password"

# A fresh CAPTCHA token is requested through CapSolver on each login attempt.
CAPSOLVER_API_KEY = ""
CAPTCHA_URL = "https://www.usvisaappt.com/visaapplicantui"
CAPTCHA_KEY = ""
ANCHOR_BASE_64 = ""
RELOAD_BASE_64 = ""

# These are updated automatically after a successful login. AUTHORIZATION_TOKEN
# is enough to skip login; REFRESH_TOKEN is persisted for future refresh support.
AUTHORIZATION_TOKEN = ""
REFRESH_TOKEN = ""

# Optional selector. Leave empty to use the most recently created application.
APPLICATION_ID = ""

# Leave empty to disable automatic booking. When set, slots strictly before
# this date are automatically booked after GET_TIME returns a slotId.
BOOKING_DATE_LIMIT = ""

POLL_INTERVAL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 30

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
