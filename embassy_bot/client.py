from __future__ import annotations

import base64
import json
import logging
import secrets
import string
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import capsolver
import requests

from embassy_bot.crypto import build_login_authorization


LOGGER = logging.getLogger(__name__)
MAX_RESPONSE_SNIPPET_LENGTH = 1000
TOKEN_EXPIRY_SKEW_SECONDS = 300
SENSITIVE_RESPONSE_HEADERS = {"authorization", "cookie", "refreshtoken", "set-cookie"}

LOGIN_URL = "https://www.usvisaappt.com/identity/user/login"
REFRESH_TOKEN_URL = "https://www.usvisaappt.com/identity/user/refreshToken"
APP_URL = "https://www.usvisaappt.com/visaapplicantui/"
DEFAULT_SLOT_REFERER = (
    "https://www.usvisaappt.com/visaapplicantui/home/appointment/slot"
)
FIRST_MONTH_URL = (
    "https://www.usvisaappt.com/visaadministrationapi/v1/modifyslot/getFirstAvailableMonth"
)
SLOT_URL = "https://www.usvisaappt.com/visaadministrationapi/v1/modifyslot/getSlotDates"
GET_TIME_URL = "https://www.usvisaappt.com/visaadministrationapi/v1/modifyslot/getSlotTime"
RESCHEDULE_URL = "https://www.usvisaappt.com/visaappointmentapi/appointments/reschedule"
LANDING_PAGE_DETAILS_URL = (
    "https://www.usvisaappt.com/visaappointmentapi/appointments/getLandingPageDeatils"
)
ORIGIN = "https://www.usvisaappt.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
SEC_CH_UA_PLATFORM = '"Windows"'
SEC_CH_UA = '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"'
SEC_CH_UA_MOBILE = "?0"
LOGIN_HEADERS = {
    "Access-Control-Max-Age": "1000",
    "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Origin": "*",
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en,fr;q=0.9",
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
    "Accept-Language": "en,fr;q=0.9",
    "Referer": ORIGIN,
}

SLOT_HEADERS = {
    "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en,fr;q=0.9",
    "Content-Type": "application/json",
    "Origin": ORIGIN,
    "Referer": DEFAULT_SLOT_REFERER,
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Priority": "u=1, i",
}

REFRESH_HEADERS = {
    "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en,fr;q=0.9",
    "Content-Type": "application/json",
    "Origin": ORIGIN,
    "Referer": DEFAULT_SLOT_REFERER,
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Priority": "u=1, i",
    "host": "www.usvisaappt.com",
}


@dataclass(frozen=True)
class SlotRequest:
    post_user_id: int
    applicant_id: str
    visa_type: str
    visa_class: str
    location_type: str
    application_id: str
    app_uuid: str

    def as_referer(self) -> str:
        query = urlencode(
            {
                "type": self.location_type,
                "appUUID": self.app_uuid,
                "applicantId": self.applicant_id,
                "ofcAppointmentDate": "",
            }
        )
        return f"{DEFAULT_SLOT_REFERER}?{query}"

    def as_first_month_json(self) -> dict[str, Any]:
        return {
            "postUserId": self.post_user_id,
            "applicantId": self.applicant_id,
            "visaType": self.visa_type,
            "visaClass": self.visa_class,
            "locationType": self.location_type,
            "applicationId": self.application_id,
        }

    def as_slot_json(self, from_date: str, to_date: str) -> dict[str, Any]:
        return {
            "fromDate": from_date,
            "toDate": to_date,
            **self.as_first_month_json(),
        }

    def as_slot_time_json(self, from_date: str, to_date: str, slot_date: str) -> dict[str, Any]:
        return {
            "applicantId": self.applicant_id,
            "applicationId": self.application_id,
            "fromDate": from_date,
            "postUserId": self.post_user_id,
            "slotDate": slot_date,
            "toDate": to_date,
            "visaClass": self.visa_class,
            "visaType": self.visa_type,
        }

    def as_reschedule_json(
        self,
        appointment_id: int,
        slot_id: str,
        appointment_date: str,
        appointment_time: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "appointmentId": appointment_id,
                "applicantUUID": None,
                "appointmentLocationType": self.location_type,
                "appointmentStatus": "SCHEDULED",
                "slotId": slot_id,
                "appointmentDt": appointment_date,
                "appointmentTime": appointment_time,
                "postUserId": self.post_user_id,
                "applicantId": self.applicant_id,
                "applicationId": self.application_id,
                "rescheduleType": self.location_type,
            }
        ]


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
        correlation_key: str | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.capsolver_api_key = capsolver_api_key
        self.captcha_url = captcha_url
        self.captcha_key = captcha_key
        self.captcha_token: str | None = None
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.authorization_token = self.normalize_authorization_token(authorization_token)
        self.refresh_token = refresh_token or None
        self.on_tokens_updated = on_tokens_updated
        self.anchor = anchor
        self.reload = reload
        self.slot_referer = slot_referer or DEFAULT_SLOT_REFERER
        self.correlation_key = correlation_key or None

    def has_authorization_token(self) -> bool:
        return bool(self.authorization_token)

    def is_authorization_token_expired(self) -> bool:
        claims = self.decode_authorization_claims()
        exp = claims.get("exp")
        if not isinstance(exp, int):
            return False
        return exp <= int(time.time()) + TOKEN_EXPIRY_SKEW_SECONDS

    def decode_authorization_claims(self) -> dict[str, Any]:
        if not self.authorization_token:
            return {}

        token = self.authorization_token
        if token.startswith("Bearer "):
            token = token.split(" ", 1)[1]
        parts = token.split(".")
        if len(parts) < 2:
            return {}

        try:
            payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except (ValueError, json.JSONDecodeError):
            return {}

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

    def refresh_authorization_token(self) -> bool:
        if not self.refresh_token:
            return False

        body = {
            "refreshToken": self.refresh_token,
            "username": self.username,
        }
        try:
            response = self.session.post(
                REFRESH_TOKEN_URL,
                headers=self._refresh_headers(),
                data=json.dumps(body, separators=(",", ":")),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            LOGGER.exception("Refresh token request failed")
            return False

        if response.status_code >= 400:
            self.log_api_failure("REFRESH_TOKEN", response)
            return False

        if not self.update_tokens_from_response(response):
            LOGGER.warning("Refresh token request succeeded but returned no Authorization header")
            return False

        LOGGER.info("Refreshed authorization token")
        return True

    def update_tokens_from_response(self, response: requests.Response) -> bool:
        authorization = self.normalize_authorization_token(response.headers.get("Authorization"))
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
        cookie_names = [cookie.name for cookie in getattr(self.session, "cookies", [])]
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

    def get_first_available_month(self, request: SlotRequest) -> Any:
        self.ensure_authorized("FIRST_MONTH")

        response = self._post_first_month(request)
        if response.status_code in {401, 403}:
            LOGGER.warning("FIRST_MONTH request was unauthorized; attempting token refresh")
            self.refresh_or_login()
            response = self._post_first_month(request)

        self.update_tokens_from_response(response)
        if response.status_code >= 400:
            self.log_api_failure("FIRST_MONTH", response)
        response.raise_for_status()
        return response.json()

    def get_slot_dates(self, request: SlotRequest, from_date: str, to_date: str) -> Any:
        self.ensure_authorized("SLOTS")

        response = self._post_slots(request, from_date, to_date)
        if response.status_code in {401, 403}:
            LOGGER.warning("SLOTS request was unauthorized; attempting token refresh")
            self.refresh_or_login()
            response = self._post_slots(request, from_date, to_date)

        self.update_tokens_from_response(response)
        if response.status_code >= 400:
            self.log_api_failure("SLOTS", response)
        response.raise_for_status()
        return response.json()

    def get_slot_times(
        self,
        request: SlotRequest,
        from_date: str,
        to_date: str,
        slot_date: str,
    ) -> Any:
        self.ensure_authorized("GET_TIME")

        response = self._post_slot_times(request, from_date, to_date, slot_date)
        if response.status_code in {401, 403}:
            LOGGER.warning("GET_TIME request was unauthorized; attempting token refresh")
            self.refresh_or_login()
            response = self._post_slot_times(request, from_date, to_date, slot_date)

        self.update_tokens_from_response(response)
        if response.status_code >= 400:
            self.log_api_failure("GET_TIME", response)
        response.raise_for_status()
        return response.json()

    def get_landing_page_details(self) -> Any:
        self.ensure_authorized("GET_LANDING_PAGE_DETAILS")

        response = self._get_landing_page_details()
        if response.status_code in {401, 403}:
            LOGGER.warning("GET_LANDING_PAGE_DETAILS request was unauthorized; attempting token refresh")
            self.refresh_or_login()
            response = self._get_landing_page_details()

        self.update_tokens_from_response(response)
        if response.status_code >= 400:
            self.log_api_failure("GET_LANDING_PAGE_DETAILS", response)
        response.raise_for_status()
        return response.json()

    def reschedule_appointment(
        self,
        request: SlotRequest,
        appointment_id: int,
        slot_id: str,
        appointment_date: str,
        appointment_time: str,
    ) -> Any:
        self.ensure_authorized("BOOKING")

        response = self._put_reschedule(
            request,
            appointment_id,
            slot_id,
            appointment_date,
            appointment_time,
        )
        if response.status_code in {401, 403}:
            LOGGER.warning("BOOKING request was unauthorized; attempting token refresh")
            self.refresh_or_login()
            response = self._put_reschedule(
                request,
                appointment_id,
                slot_id,
                appointment_date,
                appointment_time,
            )

        self.update_tokens_from_response(response)
        if response.status_code >= 400:
            self.log_api_failure("BOOKING", response)
        response.raise_for_status()
        return response.json()

    def ensure_authorized(self, label: str) -> None:
        if not self.has_authorization_token():
            LOGGER.info("No configured authorization token; attempting refresh")
            self.refresh_or_login()
        elif self.is_authorization_token_expired():
            LOGGER.info("Configured authorization token is expired or near expiry; attempting refresh")
            self.refresh_or_login()
        else:
            LOGGER.info("Using configured authorization token for %s request", label)

    def refresh_or_login(self) -> None:
        if self.refresh_authorization_token():
            return

        LOGGER.info("Falling back to full login")
        self.login()

    def log_api_failure(self, label: str, response: requests.Response) -> None:
        safe_headers = {
            name: ("<redacted>" if name.lower() in SENSITIVE_RESPONSE_HEADERS else value)
            for name, value in response.headers.items()
        }
        request = getattr(response, "request", None)
        request_headers = {
            name: ("<redacted>" if name.lower() in SENSITIVE_RESPONSE_HEADERS else value)
            for name, value in getattr(request, "headers", {}).items()
        }
        request_body = getattr(request, "body", "") or ""
        if isinstance(request_body, bytes):
            request_body = request_body.decode("utf-8", errors="replace")
        cookie_names = [cookie.name for cookie in getattr(self.session, "cookies", [])]
        snippet = getattr(response, "text", "")[:MAX_RESPONSE_SNIPPET_LENGTH].replace("\n", "\\n")
        LOGGER.error("%s failed with status %s", label, response.status_code)
        LOGGER.error("%s request headers: %s", label, request_headers)
        LOGGER.error("%s request body: %s", label, str(request_body)[:MAX_RESPONSE_SNIPPET_LENGTH])
        LOGGER.error("%s session cookie names: %s", label, cookie_names)
        LOGGER.error("%s response headers: %s", label, safe_headers)
        LOGGER.error("%s response body snippet: %s", label, snippet)

    def _authorized_post(self, url: str, body_json: dict[str, Any]) -> requests.Response:
        return self._authorized_request("POST", url, body_json)

    def _authorized_put(self, url: str, body_json: Any) -> requests.Response:
        return self._authorized_request("PUT", url, body_json)

    def _authorized_get(self, url: str) -> requests.Response:
        return self.session.get(
            url,
            headers=self._authorized_headers(),
            timeout=self.timeout_seconds,
        )

    def _authorized_request(self, method: str, url: str, body_json: Any) -> requests.Response:
        headers = self._authorized_headers()
        body = json.dumps(body_json, separators=(",", ":"))
        return self.session.request(
            method,
            url,
            headers=headers,
            data=body,
            timeout=self.timeout_seconds,
        )

    def _authorized_headers(self) -> dict[str, str]:
        headers = {
            **SLOT_HEADERS,
            "Authorization": self.authorization_token or "",
            "Referer": self.slot_referer,
            "x-correlation-key": self.correlation_key or self.generate_correlation_key(),
        }
        return headers

    def _refresh_headers(self) -> dict[str, str]:
        return {
            **REFRESH_HEADERS,
            "Referer": self.slot_referer,
        }

    def _post_first_month(self, request: SlotRequest) -> requests.Response:
        return self._authorized_post(FIRST_MONTH_URL, request.as_first_month_json())

    def _post_slots(self, request: SlotRequest, from_date: str, to_date: str) -> requests.Response:
        return self._authorized_post(SLOT_URL, request.as_slot_json(from_date, to_date))

    def _post_slot_times(
        self,
        request: SlotRequest,
        from_date: str,
        to_date: str,
        slot_date: str,
    ) -> requests.Response:
        return self._authorized_post(
            GET_TIME_URL,
            request.as_slot_time_json(from_date, to_date, slot_date),
        )

    def _get_landing_page_details(self) -> requests.Response:
        return self._authorized_get(LANDING_PAGE_DETAILS_URL)

    def _put_reschedule(
        self,
        request: SlotRequest,
        appointment_id: int,
        slot_id: str,
        appointment_date: str,
        appointment_time: str,
    ) -> requests.Response:
        return self._authorized_put(
            RESCHEDULE_URL,
            request.as_reschedule_json(
                appointment_id,
                slot_id,
                appointment_date,
                appointment_time,
            ),
        )

    @staticmethod
    def generate_correlation_key(length: int = 15) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def normalize_authorization_token(token: str | None) -> str | None:
        if not token:
            return None
        token = token.strip()
        if not token:
            return None
        if token.startswith("Bearer "):
            return token
        return f"Bearer {token}"
