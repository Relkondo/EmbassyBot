import unittest
import base64
import json
import time

from embassy_bot.client import SlotRequest, VisaAppointmentClient


class FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload if payload is not None else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return self.responses.pop(0)


class TestVisaAppointmentClient(VisaAppointmentClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captcha_requests = 0

    def get_captcha_token(self) -> str:
        self.captcha_requests += 1
        return f"captcha-{self.captcha_requests}"


def slot_request() -> SlotRequest:
    return SlotRequest(
        post_user_id=481,
        applicant_id="applicant",
        visa_type="NIV",
        visa_class="H1B",
        location_type="POST",
        application_id="application",
        app_uuid="app-uuid",
    )


def fake_jwt(exp: int) -> str:
    header = {"alg": "none"}
    payload = {"exp": exp, "token_use": "id"}

    def encode(value) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"Bearer {encode(header)}.{encode(payload)}."


class ClientTests(unittest.TestCase):
    def test_slot_request_builds_browser_slot_referer(self) -> None:
        self.assertEqual(
            slot_request().as_referer(),
            (
                "https://www.usvisaappt.com/visaapplicantui/home/appointment/slot"
                "?type=POST&appUUID=app-uuid&applicantId=applicant&ofcAppointmentDate="
            ),
        )

    def test_stored_authorization_token_skips_login(self) -> None:
        session = FakeSession([FakeResponse(payload={"slots": []})])
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token=fake_jwt(int(time.time()) + 3600),
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(len(session.requests), 1)
        self.assertEqual(client.captcha_requests, 0)
        self.assertIn("/getSlotDates", session.requests[0]["url"])
        self.assertEqual(session.requests[0]["headers"]["Authorization"], client.authorization_token)

    def test_expired_stored_authorization_token_logs_in_before_slots(self) -> None:
        session = FakeSession(
            [
                FakeResponse(),
                FakeResponse(
                    headers={
                        "Authorization": fake_jwt(int(time.time()) + 3600),
                        "Refreshtoken": "refresh fresh",
                    }
                ),
                FakeResponse(payload=[]),
            ]
        )
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token=fake_jwt(int(time.time()) - 1),
            refresh_token="refresh stored",
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(client.captcha_requests, 1)
        self.assertIn("/visaapplicantui", session.requests[0]["url"])
        self.assertIn("/identity/user/login", session.requests[1]["url"])
        self.assertIn("/getSlotDates", session.requests[2]["url"])

    def test_expired_token_relogs_and_persists_new_tokens(self) -> None:
        saved_tokens = []
        session = FakeSession(
            [
                FakeResponse(status_code=401),
                FakeResponse(),
                FakeResponse(
                    headers={
                        "Authorization": "Bearer fresh",
                        "Refreshtoken": "refresh fresh",
                    }
                ),
                FakeResponse(payload={"slots": []}),
            ]
        )
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token="Bearer expired",
            refresh_token="refresh expired",
            on_tokens_updated=lambda auth, refresh: saved_tokens.append((auth, refresh)),
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(client.captcha_requests, 1)
        self.assertEqual(saved_tokens, [("Bearer fresh", "refresh fresh")])
        self.assertIn("/visaapplicantui", session.requests[1]["url"])
        self.assertEqual(session.requests[2]["json"]["captchaToken"], "captcha-1")
        self.assertEqual(session.requests[-1]["headers"]["Authorization"], "Bearer fresh")

    def test_missing_authorization_token_logs_in_before_slots(self) -> None:
        session = FakeSession(
            [
                FakeResponse(),
                FakeResponse(
                    headers={
                        "Authorization": "Bearer fresh",
                        "Refreshtoken": "refresh fresh",
                    }
                ),
                FakeResponse(payload={"slots": []}),
            ]
        )
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            refresh_token="refresh stored",
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(client.captcha_requests, 1)
        self.assertIn("/visaapplicantui", session.requests[0]["url"])
        self.assertIn("/identity/user/login", session.requests[1]["url"])
        self.assertEqual(session.requests[1]["json"]["captchaToken"], "captcha-1")
        self.assertIn("/getSlotDates", session.requests[2]["url"])
        self.assertEqual(session.requests[2]["headers"]["Authorization"], "Bearer fresh")

    def test_slot_request_uses_configured_referer(self) -> None:
        session = FakeSession([FakeResponse(payload=[])])
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token="Bearer stored",
            slot_referer="https://www.usvisaappt.com/visaapplicantui/home/appointment/slot",
            correlation_key="BgawUL5pIjk72i0",
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(
            session.requests[0]["headers"]["Referer"],
            "https://www.usvisaappt.com/visaapplicantui/home/appointment/slot",
        )
        self.assertEqual(session.requests[0]["headers"]["x-correlation-key"], "BgawUL5pIjk72i0")

    def test_slot_request_uses_compact_json_body(self) -> None:
        session = FakeSession([FakeResponse(payload=[])])
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token=fake_jwt(int(time.time()) + 3600),
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(
            session.requests[0]["data"],
            (
                '{"fromDate":"2026-06-07","toDate":"2026-08-05","postUserId":481,'
                '"applicantId":"applicant","visaType":"NIV","visaClass":"H1B",'
                '"locationType":"POST","applicationId":"application"}'
            ),
        )

    def test_first_month_request_omits_slot_date_window(self) -> None:
        session = FakeSession([FakeResponse(payload={"present": False})])
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token=fake_jwt(int(time.time()) + 3600),
            session=session,
        )

        client.get_first_available_month(slot_request())

        self.assertEqual(
            session.requests[0]["data"],
            (
                '{"postUserId":481,"applicantId":"applicant","visaType":"NIV",'
                '"visaClass":"H1B","locationType":"POST","applicationId":"application"}'
            ),
        )

    def test_slot_response_updates_returned_tokens(self) -> None:
        saved_tokens = []
        session = FakeSession(
            [
                FakeResponse(
                    headers={
                        "Authorization": "Bearer rotated",
                        "Refreshtoken": "refresh rotated",
                    },
                    payload=[],
                )
            ]
        )
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token="Bearer stored",
            refresh_token="refresh stored",
            on_tokens_updated=lambda auth, refresh: saved_tokens.append((auth, refresh)),
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(client.authorization_token, "Bearer rotated")
        self.assertEqual(client.refresh_token, "refresh rotated")
        self.assertEqual(saved_tokens, [("Bearer rotated", "refresh rotated")])


if __name__ == "__main__":
    unittest.main()
