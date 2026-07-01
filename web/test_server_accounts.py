from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
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
        server.pin_attempts.clear()
        server.reset_attempts.clear()
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

    def test_password_reset_link_changes_password_once(self) -> None:
        self.signup()
        with self.client.session_transaction() as session:
            session["access"] = "dev"

        response = self.client.post("/api/admin/accounts/cliente@example.com/reset-link")
        self.assertEqual(response.status_code, 200)
        link = response.get_json()["reset_url"]
        token = parse_qs(urlsplit(link).query)["reset"][0]

        response = self.client.post(
            "/api/password-reset/confirm",
            json={
                "token": token,
                "password": "nova-senha",
                "password_confirm": "nova-senha",
            },
        )
        self.assertEqual(response.status_code, 200)

        self.client.post("/api/logout")
        response = self.client.post(
            "/api/login",
            json={"email": "cliente@example.com", "password": "senha-segura"},
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/api/login",
            json={"email": "cliente@example.com", "password": "nova-senha"},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/password-reset/confirm",
            json={
                "token": token,
                "password": "outra-senha",
                "password_confirm": "outra-senha",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_requires_developer_session(self) -> None:
        self.signup()
        response = self.client.get("/api/admin/accounts")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_manage_account(self) -> None:
        self.signup()
        with self.client.session_transaction() as session:
            session["access"] = "dev"

        response = self.client.get("/api/admin/accounts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["accounts"][0]["email"], "cliente@example.com")

        response = self.client.post(
            "/api/admin/accounts/cliente@example.com/company",
            json={"razao_social": "Empresa Pelo Suporte"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["razao_social"], "Empresa Pelo Suporte")

        response = self.client.post(
            "/api/admin/accounts/cliente@example.com/access",
            json={"active": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["active"])

        self.client.post("/api/logout")
        response = self.client.post(
            "/api/login",
            json={"email": "cliente@example.com", "password": "senha-segura"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["payment_required"])
        self.assertEqual(payload["razao_social"], "Empresa Pelo Suporte")

    def test_dev_pin_rate_limit(self) -> None:
        with patch.dict(os.environ, {"APP_PIN": "2749"}, clear=False):
            for _ in range(5):
                response = self.client.post("/api/dev-pin", json={"pin": "0000"})
                self.assertEqual(response.status_code, 401)

            response = self.client.post("/api/dev-pin", json={"pin": "0000"})
            self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
