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
        client = VisaAppointmentClient(
            username="user",
            password="pass",
            captcha_token="captcha",
            authorization_token="Bearer stored",
            session=session,
        )

        client.get_slot_dates(slot_request())

        self.assertEqual(len(session.requests), 1)
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
        client = VisaAppointmentClient(
            username="user",
            password="pass",
            captcha_token="captcha",
            authorization_token="Bearer expired",
            on_tokens_updated=lambda auth, refresh: saved_tokens.append((auth, refresh)),
            session=session,
        )

        client.get_slot_dates(slot_request())

        self.assertEqual(saved_tokens, [("Bearer fresh", "refresh fresh")])
        self.assertEqual(session.requests[-1]["headers"]["Authorization"], "Bearer fresh")


if __name__ == "__main__":
    unittest.main()
