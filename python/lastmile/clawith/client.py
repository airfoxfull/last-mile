"""Clawith REST + WebSocket 客户端"""

import json
import httpx
import websockets
from typing import Any

CLAWITH_URL = "http://localhost:8008"
CLAWITH_WS = "ws://localhost:8008"
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
    async with httpx.AsyncClient(base_url=CLAWITH_URL, timeout=30, follow_redirects=True) as c:
        r = await c.request(method, path, headers=_headers(), **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None


# ── Auth ──

async def login(email: str, password: str) -> dict:
    data = await _request("POST", "/api/auth/login",
                          json={"login_identifier": email, "password": password})
    set_token(data["access_token"])
    return data


# ── Agent ──

async def list_agents() -> list[dict]:
    return await _request("GET", "/api/agents/")


async def get_agent(agent_id: str) -> dict:
    return await _request("GET", f"/api/agents/{agent_id}")


# ── Agent Files ──

async def read_file(agent_id: str, path: str) -> str:
    data = await _request("GET", f"/api/agents/{agent_id}/files/content", params={"path": path})
    return data.get("content", "") if isinstance(data, dict) else str(data)


async def write_file(agent_id: str, path: str, content: str) -> None:
    await _request("PUT", f"/api/agents/{agent_id}/files/content",
                   params={"path": path}, json={"content": content})


# ── Sessions ──

async def create_session(agent_id: str, title: str = "pipeline") -> dict:
    return await _request("POST", f"/api/agents/{agent_id}/sessions/",
                          json={"title": title})


# ── Chat (WebSocket) ──

async def send_message(agent_id: str, message: str, session_id: str | None = None) -> str:
    """通过 WebSocket 发消息给 Agent，收集完整回复。"""
    if not _token:
        raise RuntimeError("未登录，请先调用 login()")

    # 如果没有 session_id，创建一个
    if not session_id:
        s = await create_session(agent_id)
        session_id = s["id"]

    url = f"{CLAWITH_WS}/ws/chat/{agent_id}?token={_token}&session_id={session_id}"
    full_response = ""

    async with websockets.connect(url) as ws:
        # 发送消息
        await ws.send(json.dumps({"content": message}))

        # 收集回复
        while True:
            try:
                raw = await ws.recv()
                data = json.loads(raw) if isinstance(raw, str) else raw

                msg_type = data.get("type", "")

                if msg_type == "chunk":
                    full_response += data.get("content", "")
                elif msg_type == "message_complete":
                    if not full_response:
                        full_response = data.get("content", "")
                    break
                elif msg_type == "done":
                    break
                elif msg_type == "error":
                    raise RuntimeError(f"Agent 错误: {data.get('content', '')}")
                elif msg_type == "tool_start":
                    # Agent 在调用工具，继续等
                    pass
                elif msg_type == "tool_result":
                    # 工具结果，继续等
                    pass
            except websockets.ConnectionClosed:
                break

    return full_response


# ── Triggers ──

async def create_webhook_trigger(agent_id: str, name: str, token: str) -> dict:
    return await _request("POST", f"/api/agents/{agent_id}/triggers/", json={
        "name": name,
        "type": "webhook",
        "config": {"token": token},
        "reason": "LangGraph workflow event",
    })


# ── Notifications ──

async def list_notifications() -> list[dict]:
    return await _request("GET", "/api/notifications/")
