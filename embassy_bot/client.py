from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from embassy_bot.crypto import build_login_authorization


LOGGER = logging.getLogger(__name__)

LOGIN_URL = "https://www.usvisaappt.com/identity/user/login"
SLOT_URL = "https://www.usvisaappt.com/visaadministrationapi/v1/modifyslot/getSlotDates"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

LOGIN_HEADERS = {
    "Access-Control-Max-Age": "1000",
    "sec-ch-ua-platform": '"macOS"',
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Origin": "*",
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Access-Control-Allow-Headers": (
        "Origin, Content-Type, X-Auth-Token, content-type,-CSRF-Token, Authorization"
    ),
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "host": "www.usvisaappt.com",
}

SLOT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Content-Type": "application/json",
}


@dataclass(frozen=True)
class SlotRequest:
    from_date: str
    to_date: str
    post_user_id: int
    applicant_id: str
    visa_type: str
    visa_class: str
    location_type: str
    application_id: str

    def as_json(self) -> dict[str, Any]:
        return {
            "fromDate": self.from_date,
            "toDate": self.to_date,
            "postUserId": self.post_user_id,
            "applicantId": self.applicant_id,
            "visaType": self.visa_type,
            "visaClass": self.visa_class,
            "locationType": self.location_type,
            "applicationId": self.application_id,
        }


class VisaAppointmentClient:
    def __init__(
        self,
        username: str,
        password: str,
        captcha_token: str,
        timeout_seconds: int = 30,
        authorization_token: str | None = None,
        refresh_token: str | None = None,
        on_tokens_updated: Callable[[str, str | None], None] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.captcha_token = captcha_token
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.authorization_token = authorization_token or None
        self.refresh_token = refresh_token or None
        self.on_tokens_updated = on_tokens_updated

    def login(self) -> None:
        if not self.captcha_token:
            raise ValueError("CAPTCHA_TOKEN must be configured before login")

        body = {
            "authorization": build_login_authorization(self.username, self.password),
            "captchaToken": self.captcha_token,
        }
        response = self.session.post(
            LOGIN_URL,
            headers=LOGIN_HEADERS,
            json=body,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        authorization = response.headers.get("Authorization")
        if not authorization:
            raise RuntimeError("Login succeeded but response did not include Authorization header")

        self.authorization_token = authorization
        self.refresh_token = response.headers.get("Refreshtoken")
        LOGGER.info("Logged in and stored authorization token")
        if self.on_tokens_updated:
            self.on_tokens_updated(self.authorization_token, self.refresh_token)

    def get_slot_dates(self, request: SlotRequest) -> Any:
        if not self.authorization_token:
            self.login()
        else:
            LOGGER.info("Using configured authorization token for slot request")

        response = self._post_slots(request)
        if response.status_code in {401, 403}:
            LOGGER.warning("Slot request was unauthorized; attempting one fresh login")
            self.login()
            response = self._post_slots(request)

        response.raise_for_status()
        return response.json()

    def _post_slots(self, request: SlotRequest) -> requests.Response:
        headers = {**SLOT_HEADERS, "Authorization": self.authorization_token or ""}
        return self.session.post(
            SLOT_URL,
            headers=headers,
            json=request.as_json(),
            timeout=self.timeout_seconds,
        )
