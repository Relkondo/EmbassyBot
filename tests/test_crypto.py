import re
import unittest

from embassy_bot.crypto import encrypt_cryptojs_compatible


class CryptoTests(unittest.TestCase):
    def test_encrypt_cryptojs_compatible_shape(self) -> None:
        encrypted = encrypt_cryptojs_compatible(
            "user@example.com:password",
            salt=bytes(range(16)),
            iv=bytes(range(16, 32)),
        ).as_cryptojs_string()

        self.assertTrue(encrypted.startswith("000102030405060708090a0b0c0d0e0f"))
        self.assertEqual(encrypted[32:64], "101112131415161718191a1b1c1d1e1f")
        self.assertRegex(encrypted, re.compile(r"^[0-9a-f]{64}[A-Za-z0-9+/]+={0,2}$"))


if __name__ == "__main__":
    unittest.main()
