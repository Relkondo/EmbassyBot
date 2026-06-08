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

    def put(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return self.responses.pop(0)

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
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


def raw_fake_jwt(exp: int) -> str:
    return fake_jwt(exp).split(" ", 1)[1]


class ClientTests(unittest.TestCase):
    def test_slot_request_builds_browser_slot_referer(self) -> None:
        self.assertEqual(
            slot_request().as_referer(),
            (
                "https://www.usvisaappt.com/visaapplicantui/home/appointment/slot"
                "?type=POST&appUUID=app-uuid&applicantId=applicant&ofcAppointmentDate="
            ),
        )

    def test_slot_request_builds_slot_time_payload(self) -> None:
        self.assertEqual(
            slot_request().as_slot_time_json("2026-06-07", "2026-08-31", "2026-08-20"),
            {
                "applicantId": "applicant",
                "applicationId": "application",
                "fromDate": "2026-06-07",
                "postUserId": 481,
                "slotDate": "2026-08-20",
                "toDate": "2026-08-31",
                "visaClass": "H1B",
                "visaType": "NIV",
            },
        )

    def test_slot_request_builds_reschedule_payload(self) -> None:
        self.assertEqual(
            slot_request().as_reschedule_json(
                2484255,
                "slot-id",
                "2026-08-20T00:00:00.000+00:00",
                "8:30 AM",
            ),
            [
                {
                    "appointmentId": 2484255,
                    "applicantUUID": None,
                    "appointmentLocationType": "POST",
                    "appointmentStatus": "SCHEDULED",
                    "slotId": "slot-id",
                    "appointmentDt": "2026-08-20T00:00:00.000+00:00",
                    "appointmentTime": "8:30 AM",
                    "postUserId": 481,
                    "applicantId": "applicant",
                    "applicationId": "application",
                    "rescheduleType": "POST",
                }
            ],
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

    def test_raw_stored_authorization_token_gets_bearer_prefix(self) -> None:
        session = FakeSession([FakeResponse(payload={"present": False})])
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token=raw_fake_jwt(int(time.time()) + 3600),
            session=session,
        )

        client.get_first_available_month(slot_request())

        self.assertTrue(client.authorization_token.startswith("Bearer "))
        self.assertEqual(session.requests[0]["headers"]["Authorization"], client.authorization_token)

    def test_token_with_less_than_five_minutes_left_is_refreshed(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    headers={
                        "Authorization": fake_jwt(int(time.time()) + 3600),
                        "Refreshtoken": "refresh fresh",
                    }
                ),
                FakeResponse(payload={"present": False}),
            ]
        )
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token=fake_jwt(int(time.time()) + 250),
            refresh_token="refresh stored",
            session=session,
        )

        client.get_first_available_month(slot_request())

        self.assertEqual(client.captcha_requests, 0)
        self.assertIn("/identity/user/refreshToken", session.requests[0]["url"])
        self.assertIn("/getFirstAvailableMonth", session.requests[1]["url"])

    def test_expired_stored_authorization_token_logs_in_before_slots(self) -> None:
        session = FakeSession(
            [
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

        self.assertEqual(client.captcha_requests, 0)
        self.assertIn("/identity/user/refreshToken", session.requests[0]["url"])
        self.assertEqual(
            json.loads(session.requests[0]["data"]),
            {"refreshToken": "refresh stored", "username": "user"},
        )
        self.assertIn("/getSlotDates", session.requests[1]["url"])

    def test_expired_token_refreshes_and_persists_new_tokens(self) -> None:
        saved_tokens = []
        session = FakeSession(
            [
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
            authorization_token=fake_jwt(int(time.time()) - 1),
            refresh_token="refresh expired",
            on_tokens_updated=lambda auth, refresh: saved_tokens.append((auth, refresh)),
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(client.captcha_requests, 0)
        self.assertEqual(saved_tokens, [("Bearer fresh", "refresh fresh")])
        self.assertIn("/identity/user/refreshToken", session.requests[0]["url"])
        self.assertEqual(session.requests[-1]["headers"]["Authorization"], "Bearer fresh")

    def test_refresh_failure_falls_back_to_full_login(self) -> None:
        saved_tokens = []
        failures = []
        successes = []
        session = FakeSession(
            [
                FakeResponse(status_code=401),
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
            authorization_token=fake_jwt(int(time.time()) + 3600),
            refresh_token="refresh expired",
            on_tokens_updated=lambda auth, refresh: saved_tokens.append((auth, refresh)),
            on_call_failed=failures.append,
            on_call_succeeded=successes.append,
            session=session,
        )

        client.get_slot_dates(slot_request(), "2026-06-07", "2026-08-05")

        self.assertEqual(client.captcha_requests, 1)
        self.assertIn("/getSlotDates", session.requests[0]["url"])
        self.assertIn("/identity/user/refreshToken", session.requests[1]["url"])
        self.assertIn("/visaapplicantui", session.requests[2]["url"])
        self.assertEqual(session.requests[3]["json"]["captchaToken"], "captcha-1")
        self.assertEqual(session.requests[-1]["headers"]["Authorization"], "Bearer fresh")
        self.assertEqual(saved_tokens, [("Bearer fresh", "refresh fresh")])
        self.assertEqual(failures[0].label, "REFRESH_TOKEN")
        self.assertEqual(failures[0].status_code, 401)
        self.assertIn("LOGIN", successes)

    def test_missing_authorization_token_refreshes_before_slots(self) -> None:
        session = FakeSession(
            [
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

        self.assertEqual(client.captcha_requests, 0)
        self.assertIn("/identity/user/refreshToken", session.requests[0]["url"])
        self.assertIn("/getSlotDates", session.requests[1]["url"])
        self.assertEqual(session.requests[1]["headers"]["Authorization"], "Bearer fresh")

    def test_missing_tokens_logs_in_before_slots(self) -> None:
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

    def test_get_slot_times_uses_compact_json_body(self) -> None:
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

        client.get_slot_times(slot_request(), "2026-06-07", "2026-08-31", "2026-08-20")

        self.assertIn("/getSlotTime", session.requests[0]["url"])
        self.assertEqual(
            session.requests[0]["data"],
            (
                '{"applicantId":"applicant","applicationId":"application","fromDate":"2026-06-07",'
                '"postUserId":481,"slotDate":"2026-08-20","toDate":"2026-08-31",'
                '"visaClass":"H1B","visaType":"NIV"}'
            ),
        )

    def test_get_landing_page_details_uses_authorized_get(self) -> None:
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

        client.get_landing_page_details()

        self.assertIn("/getLandingPageDeatils", session.requests[0]["url"])
        self.assertEqual(session.requests[0]["headers"]["Authorization"], client.authorization_token)

    def test_reschedule_appointment_uses_put_and_compact_json_body(self) -> None:
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

        client.reschedule_appointment(
            slot_request(),
            2484255,
            "slot-id",
            "2026-08-20T00:00:00.000+00:00",
            "8:30 AM",
        )

        self.assertEqual(session.requests[0]["method"], "PUT")
        self.assertIn("/appointments/reschedule", session.requests[0]["url"])
        self.assertEqual(
            session.requests[0]["data"],
            (
                '[{"appointmentId":2484255,"applicantUUID":null,'
                '"appointmentLocationType":"POST","appointmentStatus":"SCHEDULED",'
                '"slotId":"slot-id","appointmentDt":"2026-08-20T00:00:00.000+00:00",'
                '"appointmentTime":"8:30 AM","postUserId":481,"applicantId":"applicant",'
                '"applicationId":"application","rescheduleType":"POST"}]'
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

    def test_raw_response_authorization_token_gets_bearer_prefix_before_persist(self) -> None:
        saved_tokens = []
        raw_token = raw_fake_jwt(int(time.time()) + 3600)
        session = FakeSession(
            [
                FakeResponse(
                    headers={
                        "Authorization": raw_token,
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

        self.assertEqual(client.authorization_token, f"Bearer {raw_token}")
        self.assertEqual(saved_tokens, [(f"Bearer {raw_token}", "refresh rotated")])


if __name__ == "__main__":
    unittest.main()
