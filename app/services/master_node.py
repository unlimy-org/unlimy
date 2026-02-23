from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MasterServer:
    server_id: str
    country: str
    ping_ms: int
    status: str
    white_ip: str = ""
    stats: str = ""


@dataclass
class CreateConfigResult:
    task_id: str


@dataclass
class TaskStatus:
    task_id: str
    status: str
    message: str
    config_text: Optional[str] = None


class MasterNodeError(Exception):
    pass


class MasterNodeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def get_servers(self) -> list[MasterServer]:
        data = await self._request("GET", "/servers")
        items = data.get("servers") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [self._parse_server(item) for item in items if isinstance(item, dict)]

    async def create_config(self, payload: dict[str, Any]) -> CreateConfigResult:
        data = await self._request("POST", "/configs/create", json=payload)
        task_id = str(data.get("task_id") or data.get("id") or "")
        if not task_id:
            raise MasterNodeError(f"Master node response has no task_id: {data}")
        return CreateConfigResult(task_id=task_id)

    async def get_task_status(self, task_id: str) -> TaskStatus:
        data = await self._request("GET", f"/tasks/{task_id}")
        status = str(data.get("status") or "pending").lower()
        message = str(data.get("message") or "")
        config_text = data.get("config") or data.get("config_text")
        if config_text is not None:
            config_text = str(config_text)
        return TaskStatus(
            task_id=task_id,
            status=status,
            message=message,
            config_text=config_text,
        )

    async def request_config_renew(self, payload: dict[str, Any]) -> CreateConfigResult:
        data = await self._request("POST", "/configs/renew", json=payload)
        task_id = str(data.get("task_id") or data.get("id") or "")
        if not task_id:
            raise MasterNodeError(f"Master node response has no task_id: {data}")
        return CreateConfigResult(task_id=task_id)

    async def _request(self, method: str, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        timeout = httpx.Timeout(12.0, connect=5.0)
        logger.info("master_node_request method=%s path=%s", method, path)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, f"{self.base_url}{path}", json=json)
        logger.info("master_node_response method=%s path=%s status=%s", method, path, response.status_code)
        if response.status_code >= 400:
            logger.error(
                "master_node_http_error method=%s path=%s status=%s body=%s",
                method,
                path,
                response.status_code,
                response.text[:250],
            )
            raise MasterNodeError(f"Master node HTTP {response.status_code}: {response.text[:250]}")
        try:
            body = response.json()
        except Exception as exc:
            logger.exception("master_node_invalid_json method=%s path=%s", method, path)
            raise MasterNodeError(f"Master node invalid JSON: {exc}") from exc
        if isinstance(body, dict) and body.get("ok") is False:
            logger.error("master_node_api_error method=%s path=%s body=%s", method, path, body)
            raise MasterNodeError(f"Master node API error: {body}")
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        return body

    @staticmethod
    def _parse_server(item: dict[str, Any]) -> MasterServer:
        server_id = str(item.get("server_id") or item.get("id") or item.get("name") or "unknown")
        country = str(item.get("country") or "").lower()
        if not country and "-" in server_id:
            country = server_id.split("-", 1)[0].lower()
        ping_raw = item.get("ping_ms")
        if ping_raw is None:
            ping_raw = item.get("ping")
        try:
            ping_ms = int(float(ping_raw))
        except (TypeError, ValueError):
            ping_ms = 9999
        status = str(item.get("status") or "unknown").lower()
        return MasterServer(
            server_id=server_id,
            country=country,
            ping_ms=ping_ms,
            status=status,
            white_ip=str(item.get("white_ip") or ""),
            stats=str(item.get("stats") or ""),
        )
