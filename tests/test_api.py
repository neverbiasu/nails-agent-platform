"""FastAPI endpoint tests (no API key required, uses rule-based fallback)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from nails_agent.api.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "data_sources" in data


@pytest.mark.asyncio
async def test_sources_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/sources")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@pytest.mark.asyncio
async def test_styles_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/styles")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_pipeline_list_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/pipeline/list")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_memory_search_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/memory/search", params={"q": "猫眼", "limit": 5})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_trigger_pipeline_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/trigger",
            json={"source": "manual", "keywords": ["法式甲", "猫眼"], "goal": "冲爆款"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "trigger_id" in data
    assert data["status"] == "queued"
    assert len(data["trigger_id"]) > 0


@pytest.mark.asyncio
async def test_events_endpoint_returns_trigger_event():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Fire a trigger first
        trigger_resp = await client.post(
            "/api/v1/trigger",
            json={"source": "test", "keywords": ["渐变色"]},
        )
        trigger_id = trigger_resp.json()["trigger_id"]

        # Poll events for that trigger
        events_resp = await client.get("/api/v1/events", params={"trigger_id": trigger_id})

    assert events_resp.status_code == 200
    body = events_resp.json()
    assert "events" in body
    assert len(body["events"]) >= 1
    # First event must always be TriggerEvent
    first = body["events"][0]
    assert first["event_type"] == "TriggerEvent"
    assert first["trigger_id"] == trigger_id
    assert first["agent_id"] == "TriggerGateway"
