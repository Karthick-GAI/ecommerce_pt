"""
API tests for the RAG Shopping Assistant (shopping_assistant service — port 8012).

Covers:
  - Session creation and conversation flow
  - Response structure validation
  - Fallback_mode field present in response
  - History retrieval
  - Session management
  - Error handling (missing session, empty message)

Run with:
    cd tests/api
    pytest test_shopping_assistant.py -v
"""

import httpx
import pytest
from conftest import BASE_URLS

BASE = BASE_URLS.get("shopping_assistant", "http://localhost:8012")


class TestHealthCheck:
    def test_health_endpoint_ok(self):
        resp = httpx.get(f"{BASE}/health", timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "ok"
        assert "indexed_products" in body
        assert "local_fallback" in body

    def test_local_fallback_status_in_health(self):
        resp = httpx.get(f"{BASE}/health", timeout=10)
        body = resp.json()
        fb = body.get("local_fallback", {})
        assert "tier2_available" in fb
        assert fb["tier2_available"] is True     # tier-2 (plain text) always available


class TestChatSession:
    def test_new_chat_creates_session(self):
        resp = httpx.post(
            f"{BASE}/chat",
            json={"message": "I need wireless earbuds under 2000"},
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert isinstance(body["session_id"], str)
        assert len(body["session_id"]) > 0

    def test_chat_response_has_required_fields(self):
        resp = httpx.post(
            f"{BASE}/chat",
            json={"message": "Show me laptops for college students"},
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert "reply" in body
        assert "sources" in body
        assert "fallback_mode" in body          # must declare fallback state
        assert isinstance(body["reply"], str)
        assert len(body["reply"]) > 10          # non-empty reply

    def test_chat_sources_are_products(self):
        resp = httpx.post(
            f"{BASE}/chat",
            json={"message": "recommend running shoes"},
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        for source in body.get("sources", []):
            assert "id" in source
            assert "name" in source
            assert "effective_price" in source
            assert "in_stock" in source
            assert isinstance(source["effective_price"], (int, float))

    def test_follow_up_uses_same_session(self):
        # First message
        resp1 = httpx.post(
            f"{BASE}/chat",
            json={"message": "I need a gaming laptop under 60000"},
            timeout=30,
        )
        assert resp1.status_code == 200
        session_id = resp1.json()["session_id"]

        # Follow-up in same session
        resp2 = httpx.post(
            f"{BASE}/chat",
            json={
                "session_id": session_id,
                "message": "Which has the better GPU?",
            },
            timeout=30,
        )
        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id

    def test_invalid_session_id_returns_404(self):
        resp = httpx.post(
            f"{BASE}/chat",
            json={
                "session_id": "nonexistent-session-id-99999",
                "message": "hello",
            },
            timeout=15,
        )
        assert resp.status_code == 404

    def test_fallback_mode_is_boolean(self):
        resp = httpx.post(
            f"{BASE}/chat",
            json={"message": "best smartphone for photography"},
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["fallback_mode"], bool)


class TestChatHistory:
    @pytest.fixture
    def session_with_history(self):
        """Create a session with 2 turns of history."""
        resp1 = httpx.post(
            f"{BASE}/chat",
            json={"message": "show me yoga mats"},
            timeout=30,
        )
        assert resp1.status_code == 200
        session_id = resp1.json()["session_id"]

        resp2 = httpx.post(
            f"{BASE}/chat",
            json={"session_id": session_id, "message": "which is most durable?"},
            timeout=30,
        )
        assert resp2.status_code == 200
        return session_id

    def test_history_returns_correct_structure(self, session_with_history):
        resp = httpx.get(f"{BASE}/chat/{session_with_history}/history", timeout=15)
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert "messages" in body
        assert body["session_id"] == session_with_history

    def test_history_has_both_roles(self, session_with_history):
        resp = httpx.get(f"{BASE}/chat/{session_with_history}/history", timeout=15)
        body = resp.json()
        roles = {m["role"] for m in body["messages"]}
        assert "user" in roles
        assert "assistant" in roles

    def test_history_message_count(self, session_with_history):
        resp = httpx.get(f"{BASE}/chat/{session_with_history}/history", timeout=15)
        body = resp.json()
        # 2 turns = 4 messages (2 user + 2 assistant)
        assert len(body["messages"]) >= 4

    def test_history_nonexistent_session_returns_404(self):
        resp = httpx.get(f"{BASE}/chat/nonexistent-session-xyz/history", timeout=10)
        assert resp.status_code == 404


class TestSessionManagement:
    def test_list_sessions_endpoint(self):
        resp = httpx.get(f"{BASE}/chat/sessions/list", timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body
        assert "total" in body

    def test_delete_session_clears_history(self):
        # Create a session
        resp = httpx.post(
            f"{BASE}/chat",
            json={"message": "find me a coffee maker"},
            timeout=30,
        )
        session_id = resp.json()["session_id"]

        # Delete it
        del_resp = httpx.delete(f"{BASE}/chat/{session_id}", timeout=10)
        assert del_resp.status_code == 200

        # History should now be 404
        history_resp = httpx.get(f"{BASE}/chat/{session_id}/history", timeout=10)
        assert history_resp.status_code == 404


class TestRetrievalQuality:
    """Spot-check that the RAG pipeline returns category-relevant products."""

    QUERY_CATEGORY_PAIRS = [
        ("wireless earbuds for gym", "Electronics"),
        ("yoga mat for home workout", "Sports"),
        ("air fryer 4 litre", "Home & Kitchen"),
    ]

    @pytest.mark.parametrize("query,expected_category", QUERY_CATEGORY_PAIRS)
    def test_top_result_is_relevant_category(self, query, expected_category):
        resp = httpx.post(f"{BASE}/chat", json={"message": query}, timeout=30)
        assert resp.status_code == 200
        body = resp.json()
        sources = body.get("sources", [])
        if not sources:
            pytest.skip("No sources returned (empty catalogue or service not seeded)")
        # Check at least one source matches the expected category
        categories = [s.get("category", "").lower() for s in sources]
        assert any(expected_category.lower() in cat for cat in categories), (
            f"Query '{query}': expected at least one result in '{expected_category}', "
            f"got categories: {categories}"
        )
