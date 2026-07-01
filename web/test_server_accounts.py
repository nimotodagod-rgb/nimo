from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class AccountFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.accounts_file = Path(self.temp_dir.name) / "users.json"
        self.environment = patch.dict(
            os.environ,
            {
                "APP_ACCOUNTS_FILE": str(self.accounts_file),
                "APP_PAID_EMAILS": "",
                "APP_PAYMENT_URL": "",
                "DATABASE_URL": "",
            },
            clear=False,
        )
        self.environment.start()
        server.app.config.update(TESTING=True, SECRET_KEY="account-flow-test")
        self.client = server.app.test_client()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp_dir.cleanup()

    def signup(self, email: str = "cliente@example.com"):
        return self.client.post(
            "/api/signup",
            json={
                "name": "Cliente Teste",
                "email": email,
                "password": "senha-segura",
                "password_confirm": "senha-segura",
            },
        )

    def test_account_survives_logout_and_login(self) -> None:
        response = self.signup()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.accounts_file.is_file())

        self.client.post("/api/logout")
        response = self.client.post(
            "/api/login",
            json={"email": "cliente@example.com", "password": "senha-segura"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["payment_required"])

    def test_unpaid_account_is_blocked_until_activated(self) -> None:
        self.signup()
        response = self.client.post("/api/parse", json={"text": "teste"})
        self.assertEqual(response.status_code, 402)

        server.set_account_active(
            "cliente@example.com",
            True,
            payment_status="authorized",
            mercadopago_subscription_id="subscription-test",
        )
        response = self.client.get("/api/session")
        session = response.get_json()
        self.assertFalse(session["payment_required"])
        self.assertEqual(session["role"], "user")

    def test_first_company_name_is_locked_to_paid_account(self) -> None:
        self.signup()
        server.set_account_active("cliente@example.com", True)

        response = self.client.post(
            "/api/account-razao",
            json={"razao_social": "Empresa Original Ltda"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["razao_social"], "Empresa Original Ltda")

        response = self.client.post(
            "/api/account-razao",
            json={"razao_social": "Outra Empresa Ltda"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["razao_social"], "Empresa Original Ltda")


if __name__ == "__main__":
    unittest.main()
