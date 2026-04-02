"""Clawith REST API 客户端"""

import httpx
from typing import Any

CLAWITH_URL = "http://localhost:8008"
_token: str | None = None


def set_token(token: str):
    global _token
    _token = token


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if _token:
        h["Authorization"] = f"Bearer {_token}"
    return h


async def _request(method: str, path: str, **kwargs) -> Any:
    async with httpx.AsyncClient(base_url=CLAWITH_URL, timeout=30) as c:
        r = await c.request(method, path, headers=_headers(), **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None


# ── Auth ──

async def login(username: str, password: str) -> dict:
    data = await _request("POST", "/api/auth/login", json={"username": username, "password": password})
    set_token(data["access_token"])
    return data


# ── Agent ──

async def list_agents() -> list[dict]:
    return await _request("GET", "/api/agents")


async def get_agent(agent_id: str) -> dict:
    return await _request("GET", f"/api/agents/{agent_id}")


# ── Agent Files ──

async def read_file(agent_id: str, path: str) -> str:
    data = await _request("GET", f"/api/agents/{agent_id}/files/content", params={"path": path})
    return data.get("content", "") if isinstance(data, dict) else str(data)


async def write_file(agent_id: str, path: str, content: str) -> None:
    await _request("PUT", f"/api/agents/{agent_id}/files/content", params={"path": path}, json={"content": content})


# ── Chat (send message to agent, get response) ──

async def send_message(agent_id: str, message: str, session_id: str | None = None) -> dict:
    """Send a message to an agent and get the response.
    Uses the REST chat endpoint (non-streaming) for simplicity."""
    payload: dict[str, Any] = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    return await _request("POST", f"/api/agents/{agent_id}/chat", json=payload)


# ── Triggers ──

async def create_webhook_trigger(agent_id: str, name: str, token: str) -> dict:
    return await _request("POST", f"/api/agents/{agent_id}/triggers", json={
        "name": name,
        "type": "webhook",
        "config": {"token": token},
        "reason": "LangGraph workflow event",
    })


# ── Notifications / Approvals ──

async def list_notifications() -> list[dict]:
    return await _request("GET", "/api/notifications")
