from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import capsolver
import requests

from embassy_bot.crypto import build_login_authorization


LOGGER = logging.getLogger(__name__)
MAX_RESPONSE_SNIPPET_LENGTH = 1000
SENSITIVE_RESPONSE_HEADERS = {"authorization", "cookie", "refreshtoken", "set-cookie"}

LOGIN_URL = "https://www.usvisaappt.com/identity/user/login"
APP_URL = "https://www.usvisaappt.com/visaapplicantui/"
DEFAULT_SLOT_REFERER = (
    "https://www.usvisaappt.com/visaapplicantui/home/appointment/slot"
)
SLOT_URL = "https://www.usvisaappt.com/visaadministrationapi/v1/modifyslot/getSlotDates"
ORIGIN = "https://www.usvisaappt.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
LOGIN_HEADERS = {
    "Access-Control-Max-Age": "1000",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    "sec-ch-ua-mobile": "?0",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Origin": "*",
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": ORIGIN,
    "Referer": APP_URL,
    "Access-Control-Allow-Headers": (
        "Origin, Content-Type, X-Auth-Token, content-type,-CSRF-Token, Authorization"
    ),
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "host": "www.usvisaappt.com",
}

APP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ORIGIN,
}

SLOT_HEADERS = {
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    "sec-ch-ua-mobile": "?0",
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": ORIGIN,
    "Referer": DEFAULT_SLOT_REFERER,
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
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

    def as_referer(self) -> str:
        query = urlencode(
            {
                "type": self.location_type,
                "appUUID": self.application_id,
                "applicantId": self.applicant_id,
                "ofcAppointmentDate": "",
            }
        )
        return f"{DEFAULT_SLOT_REFERER}?{query}"

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
        capsolver_api_key: str,
        captcha_url: str,
        captcha_key: str,
        timeout_seconds: int = 30,
        authorization_token: str | None = None,
        refresh_token: str | None = None,
        on_tokens_updated: Callable[[str, str | None], None] | None = None,
        session: requests.Session | None = None,
        anchor: str | None = None,
        reload: str | None = None,
        slot_referer: str | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.capsolver_api_key = capsolver_api_key
        self.captcha_url = captcha_url
        self.captcha_key = captcha_key
        self.captcha_token: str | None = None
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.authorization_token = authorization_token or None
        self.refresh_token = refresh_token or None
        self.on_tokens_updated = on_tokens_updated
        self.anchor = anchor
        self.reload = reload
        self.slot_referer = slot_referer or DEFAULT_SLOT_REFERER

    def has_authorization_token(self) -> bool:
        return bool(self.authorization_token)

    def login(self) -> None:
        self.warm_up_login_session()
        self.captcha_token = self.get_captcha_token()
        if not self.captcha_token:
            raise ValueError("Failed to get CAPTCHA token")

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
        if response.status_code >= 400:
            self.log_login_failure(response)
        response.raise_for_status()

        if not self.update_tokens_from_response(response):
            raise RuntimeError("Login succeeded but response did not include Authorization header")

        LOGGER.info("Logged in and stored authorization token")

    def update_tokens_from_response(self, response: requests.Response) -> bool:
        authorization = response.headers.get("Authorization")
        refresh_token = response.headers.get("Refreshtoken")
        if not authorization:
            return False

        changed = (
            authorization != self.authorization_token
            or (refresh_token is not None and refresh_token != self.refresh_token)
        )
        self.authorization_token = authorization
        if refresh_token is not None:
            self.refresh_token = refresh_token

        if changed and self.on_tokens_updated:
            self.on_tokens_updated(self.authorization_token, self.refresh_token)
            request = getattr(response, "request", None)
            request_url = getattr(request, "url", "<unknown>")
            LOGGER.info("Persisted authorization tokens returned by %s", request_url)
        return True

    def warm_up_login_session(self) -> None:
        response = self.session.get(
            APP_URL,
            headers=APP_HEADERS,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        LOGGER.info("Warmed up login session from app page")

    def log_login_failure(self, response: requests.Response) -> None:
        safe_headers = {
            name: ("<redacted>" if name.lower() in SENSITIVE_RESPONSE_HEADERS else value)
            for name, value in response.headers.items()
        }
        cookie_names = [cookie.name for cookie in self.session.cookies]
        snippet = response.text[:MAX_RESPONSE_SNIPPET_LENGTH].replace("\n", "\\n")
        LOGGER.error("LOGIN failed with status %s", response.status_code)
        LOGGER.error("LOGIN response headers: %s", safe_headers)
        LOGGER.error("LOGIN session cookie names: %s", cookie_names)
        LOGGER.error("LOGIN response body snippet: %s", snippet)

    def get_captcha_token(self) -> str:
        if not (self.capsolver_api_key and self.captcha_url and self.captcha_key):
            raise ValueError("CapSolver API key, CAPTCHA URL, and CAPTCHA key must be configured")
        capsolver.api_key = self.capsolver_api_key
        task = {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": self.captcha_url,
            "websiteKey": self.captcha_key,
        }
        if self.anchor:
            task["anchor"] = self.anchor
        if self.reload:
            task["reload"] = self.reload

        result = capsolver.solve(task)
        if isinstance(result, dict):
            return result.get("gRecaptchaResponse") or result.get("token") or ""
        else:
            LOGGER.error(result)
        return ""

    def get_slot_dates(self, request: SlotRequest) -> Any:
        if not self.has_authorization_token():
            self.login()
        else:
            LOGGER.info("Using configured authorization token for slot request")

        response = self._post_slots(request)
        if response.status_code in {401, 403}:
            LOGGER.warning("Slot request was unauthorized; attempting one fresh login")
            self.login()
            response = self._post_slots(request)

        self.update_tokens_from_response(response)
        if response.status_code >= 400:
            self.log_slot_failure(response)
        response.raise_for_status()
        return response.json()

    def log_slot_failure(self, response: requests.Response) -> None:
        safe_headers = {
            name: ("<redacted>" if name.lower() in SENSITIVE_RESPONSE_HEADERS else value)
            for name, value in response.headers.items()
        }
        request_headers = {
            name: ("<redacted>" if name.lower() in SENSITIVE_RESPONSE_HEADERS else value)
            for name, value in response.request.headers.items()
        }
        request_body = response.request.body or ""
        if isinstance(request_body, bytes):
            request_body = request_body.decode("utf-8", errors="replace")
        cookie_names = [cookie.name for cookie in self.session.cookies]
        snippet = response.text[:MAX_RESPONSE_SNIPPET_LENGTH].replace("\n", "\\n")
        LOGGER.error("SLOTS failed with status %s", response.status_code)
        LOGGER.error("SLOTS request headers: %s", request_headers)
        LOGGER.error("SLOTS request body: %s", str(request_body)[:MAX_RESPONSE_SNIPPET_LENGTH])
        LOGGER.error("SLOTS session cookie names: %s", cookie_names)
        LOGGER.error("SLOTS response headers: %s", safe_headers)
        LOGGER.error("SLOTS response body snippet: %s", snippet)

    def _post_slots(self, request: SlotRequest) -> requests.Response:
        headers = {
            **SLOT_HEADERS,
            "Authorization": self.authorization_token or "",
            "Referer": self.slot_referer,
        }
        return self.session.post(
            SLOT_URL,
            headers=headers,
            json=request.as_json(),
            timeout=self.timeout_seconds,
        )
