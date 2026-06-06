import unittest

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


class TestVisaAppointmentClient(VisaAppointmentClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captcha_requests = 0

    def get_captcha_token(self) -> str:
        self.captcha_requests += 1
        return f"captcha-{self.captcha_requests}"


def slot_request() -> SlotRequest:
    return SlotRequest(
        from_date="2026-06-07",
        to_date="2026-08-05",
        post_user_id=481,
        applicant_id="applicant",
        visa_type="NIV",
        visa_class="H1B",
        location_type="POST",
        application_id="application",
    )


class ClientTests(unittest.TestCase):
    def test_stored_authorization_token_skips_login(self) -> None:
        session = FakeSession([FakeResponse(payload={"slots": []})])
        client = TestVisaAppointmentClient(
            username="user",
            password="pass",
            capsolver_api_key="api-key",
            captcha_url="captcha-url",
            captcha_key="captcha-key",
            authorization_token="Bearer stored",
            session=session,
        )

        client.get_slot_dates(slot_request())

        self.assertEqual(len(session.requests), 1)
        self.assertEqual(client.captcha_requests, 0)
        self.assertIn("/getSlotDates", session.requests[0]["url"])
        self.assertEqual(session.requests[0]["headers"]["Authorization"], "Bearer stored")

    def test_expired_token_relogs_and_persists_new_tokens(self) -> None:
        saved_tokens = []
        session = FakeSession(
            [
                FakeResponse(status_code=401),
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

        client.get_slot_dates(slot_request())

        self.assertEqual(client.captcha_requests, 1)
        self.assertEqual(saved_tokens, [("Bearer fresh", "refresh fresh")])
        self.assertEqual(session.requests[1]["json"]["captchaToken"], "captcha-1")
        self.assertEqual(session.requests[-1]["headers"]["Authorization"], "Bearer fresh")

    def test_missing_authorization_token_logs_in_before_slots(self) -> None:
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

        client.get_slot_dates(slot_request())

        self.assertEqual(client.captcha_requests, 1)
        self.assertIn("/identity/user/login", session.requests[0]["url"])
        self.assertEqual(session.requests[0]["json"]["captchaToken"], "captcha-1")
        self.assertIn("/getSlotDates", session.requests[1]["url"])
        self.assertEqual(session.requests[1]["headers"]["Authorization"], "Bearer fresh")


if __name__ == "__main__":
    unittest.main()
