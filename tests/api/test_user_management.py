import httpx
import pytest
from conftest import BASE_URLS, TEST_USER

BASE = BASE_URLS["user_management"]


class TestRegistration:
    def test_register_new_user(self):
        payload = {
            "email": "new_register_test@example.com",
            "password": "NewPass@2024",
            "full_name": "New Tester",
            "phone": "9000000001",
        }
        resp = httpx.post(f"{BASE}/auth/register", json=payload)
        assert resp.status_code in (201, 409), resp.text

    def test_register_duplicate_email(self):
        # Second registration with same email must return 409
        httpx.post(f"{BASE}/auth/register", json={
            "email": "dup_test@example.com",
            "password": "AnyPass@2024",
            "full_name": "Dup User",
            "phone": "9000000002",
        })
        resp = httpx.post(f"{BASE}/auth/register", json={
            "email": "dup_test@example.com",
            "password": "AnyPass@2024",
            "full_name": "Dup User",
            "phone": "9000000002",
        })
        assert resp.status_code == 409

    def test_register_rate_limit(self):
        # 4th attempt within a minute should be rate-limited
        for _ in range(3):
            httpx.post(f"{BASE}/auth/register", json={
                "email": f"rl_test_{_}@example.com",
                "password": "RateTest@2024",
                "full_name": "RL User",
                "phone": "9000000003",
            })
        resp = httpx.post(f"{BASE}/auth/register", json={
            "email": "rl_test_4@example.com",
            "password": "RateTest@2024",
            "full_name": "RL User",
            "phone": "9000000004",
        })
        assert resp.status_code == 429


class TestLogin:
    def test_login_success(self):
        resp = httpx.post(f"{BASE}/auth/login", json={
            "email": TEST_USER["email"],
            "password": TEST_USER["password"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    def test_login_wrong_password(self):
        resp = httpx.post(f"{BASE}/auth/login", json={
            "email": TEST_USER["email"],
            "password": "WrongPassword123",
        })
        assert resp.status_code == 401

    def test_login_unknown_email(self):
        resp = httpx.post(f"{BASE}/auth/login", json={
            "email": "nobody@nowhere.com",
            "password": "AnyPass@2024",
        })
        assert resp.status_code == 401


class TestProfile:
    def test_get_profile(self, auth_headers):
        resp = httpx.get(f"{BASE}/users/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == TEST_USER["email"]

    def test_update_profile(self, auth_headers):
        resp = httpx.put(f"{BASE}/users/me", json={"full_name": "Updated Tester"}, headers=auth_headers)
        assert resp.status_code == 200

    def test_unauthenticated_profile(self):
        resp = httpx.get(f"{BASE}/users/me")
        assert resp.status_code == 401


class TestGDPR:
    def test_data_export(self, auth_headers):
        resp = httpx.get(f"{BASE}/users/me/data-export", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Must include standard PII fields
        assert "email" in body
        assert "full_name" in body
        assert "addresses" in body

    def test_data_export_no_raw_card_numbers(self, auth_headers):
        resp = httpx.get(f"{BASE}/users/me/data-export", headers=auth_headers)
        body = resp.json()
        for pm in body.get("payment_methods", []):
            # Raw card numbers must never appear; only last_four and token
            assert "card_number" not in pm
            assert len(pm.get("last_four", "0000")) == 4


class TestTokenRefresh:
    def test_refresh_token(self):
        login_resp = httpx.post(f"{BASE}/auth/login", json={
            "email": TEST_USER["email"],
            "password": TEST_USER["password"],
        })
        refresh_token = login_resp.json()["refresh_token"]
        resp = httpx.post(f"{BASE}/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_invalid_refresh_token(self):
        resp = httpx.post(f"{BASE}/auth/refresh", json={"refresh_token": "not.a.valid.token"})
        assert resp.status_code == 401
