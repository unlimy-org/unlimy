from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# --- Legacy / mock master node (e.g. :6767) ---


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


# --- VPN Gateway API (e.g. :8000, /api/v1/, X-Api-Key) ---


@dataclass
class HealthResponse:
    status: str
    service: str
    environment: str


@dataclass
class AddSubscriptionRequest:
    order_id: str
    telegram_user_id: int
    duration_days: Optional[int] = None
    total_gb: Optional[int] = None
    limit_ip: Optional[int] = None
    preferred_server: Optional[str] = None
    preferred_servers: Optional[list[str]] = None
    preferred_inbound_id: Optional[int] = None
    plan_code: Optional[str] = None
    note: Optional[str] = None


@dataclass
class AddSubscriptionResponse:
    server_name: str
    client_uuid: str
    email: str
    inbound_id: int
    inbound_remark: str
    host: str
    port: int
    total_gb: int
    limit_ip: int
    expires_at: Optional[str] = None
    vless_uri: str = ""
    order_id: str = ""
    created: bool = False
    duration_days: int = 0


@dataclass
class AddSubscriptionFullResponse:
    order_id: str
    subscription_url: str
    duration_days: int
    expires_at: Optional[str]
    connections: list[AddSubscriptionResponse]


@dataclass
class RenewSubscriptionRequest:
    duration_days: int
    server_name: Optional[str] = None
    email: Optional[str] = None
    client_uuid: Optional[str] = None
    telegram_user_id: Optional[int] = None
    order_id: Optional[str] = None
    total_gb: Optional[int] = None
    limit_ip: Optional[int] = None


@dataclass
class RenewSubscriptionResponse:
    server_name: str
    client_uuid: str
    email: str
    inbound_id: int
    inbound_remark: str
    host: str
    port: int
    total_gb: int
    limit_ip: int
    expires_at: Optional[str] = None
    vless_uri: str = ""
    renewed: bool = False
    duration_days_added: int = 0
    duration_days_total: int = 0


@dataclass
class DeleteSubscriptionRequest:
    server_name: Optional[str] = None
    email: Optional[str] = None
    client_uuid: Optional[str] = None
    telegram_user_id: Optional[int] = None
    order_id: Optional[str] = None


@dataclass
class DeleteSubscriptionResponse:
    deleted: bool
    server_name: str
    client_uuid: str
    email: str
    inbound_id: int


@dataclass
class UserCreate:
    tg_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    language: str = "en"


@dataclass
class UserResponse:
    id: int
    tg_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    language: str = "en"
    created_at: Optional[str] = None


@dataclass
class PlanResponse:
    id: int
    name: str
    duration_days: int
    price_usd: float
    device_limit: int
    data_limit_gb: int


@dataclass
class ServerCreate:
    name: str
    base_url: str
    username: str
    password: str
    country: Optional[str] = None
    ip_address: Optional[str] = None
    ram: Optional[str] = None
    cpu: Optional[str] = None
    disk: Optional[str] = None
    status: str = "active"
    login_path: str = "/login"
    api_prefix: str = "/panel/api"
    public_host: Optional[str] = None
    weight: int = 1
    enabled: bool = True


@dataclass
class ServerResponse:
    id: int
    name: str
    country: str
    ip_address: str
    ram: Optional[str] = None
    cpu: Optional[str] = None
    disk: Optional[str] = None
    status: str = ""
    weight: int = 1
    enabled: bool = True
    created_at: Optional[str] = None


@dataclass
class ConnectionCreate:
    tg_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    language: str = "en"
    country: Optional[str] = None
    plan_id: Optional[int] = None
    duration_days: Optional[int] = None
    total_gb: Optional[int] = None
    limit_ip: Optional[int] = None


@dataclass
class ConnectionResponse:
    id: int
    user_id: int
    server_id: int
    order_id: int
    server_name: str
    protocol: str
    client_uuid: str
    inbound_id: int
    total_gb: int
    limit_ip: int
    created_at: str
    expires_at: str
    country: Optional[str] = None
    vless_uri: Optional[str] = None


@dataclass
class ConnectionUpdate:
    duration_days: Optional[int] = None
    total_gb: Optional[int] = None
    limit_ip: Optional[int] = None


@dataclass
class SubscriptionCreateResponse:
    order_id: int
    duration_days: int
    expires_at: str
    connections: list[ConnectionResponse]


@dataclass
class ConnectionStatsResponse:
    total_connections: int
    active_connections: int
    by_country: list[Any]
    top_users_by_connections: list[Any]


class MasterNodeError(Exception):
    pass


class MasterNodeClient:
    """Client for VPN gateway API (/api/v1/* with X-Api-Key header).
    Legacy methods (create_config, get_task_status, request_config_renew) kept for
    backwards compatibility but are deprecated — use add_subscription/renew_subscription.
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip() or None

    async def get_servers(self) -> list[MasterServer]:
        data = await self._request("GET", "/api/v1/servers", unwrap_result=False)
        items = data if isinstance(data, list) else (data.get("servers") if isinstance(data, dict) else [])
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

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
        *,
        unwrap_result: bool = True,
    ) -> Any:
        timeout = httpx.Timeout(12.0, connect=5.0)
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        logger.info("master_node_request method=%s path=%s", method, path)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method, f"{self.base_url}{path}", json=json, headers=headers or None
            )
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
        if response.status_code == 204:
            return None
        if not response.text.strip():
            return None
        try:
            body = response.json()
        except Exception as exc:
            logger.exception("master_node_invalid_json method=%s path=%s", method, path)
            raise MasterNodeError(f"Master node invalid JSON: {exc}") from exc
        if unwrap_result and isinstance(body, dict) and body.get("ok") is False:
            logger.error("master_node_api_error method=%s path=%s body=%s", method, path, body)
            raise MasterNodeError(f"Master node API error: {body}")
        if unwrap_result and isinstance(body, dict) and "result" in body:
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
            white_ip=str(item.get("white_ip") or item.get("ip_address") or ""),
            stats=str(item.get("stats") or ""),
        )

    # --- VPN Gateway API (/api/v1/, requires api_key) ---

    async def healthcheck(self) -> HealthResponse:
        """GET /healthz (no auth)."""
        data = await self._request("GET", "/healthz", unwrap_result=False)
        if not isinstance(data, dict):
            raise MasterNodeError(f"Unexpected health response: {data}")
        return HealthResponse(
            status=str(data.get("status", "ok")),
            service=str(data.get("service", "")),
            environment=str(data.get("environment", "")),
        )

    def _dict_to_add_subscription_response(self, d: dict[str, Any]) -> AddSubscriptionResponse:
        return AddSubscriptionResponse(
            server_name=str(d.get("server_name", "")),
            client_uuid=str(d.get("client_uuid", "")),
            email=str(d.get("email", "")),
            inbound_id=int(d.get("inbound_id", 0)),
            inbound_remark=str(d.get("inbound_remark", "")),
            host=str(d.get("host", "")),
            port=int(d.get("port", 0)),
            total_gb=int(d.get("total_gb", 0)),
            limit_ip=int(d.get("limit_ip", 0)),
            expires_at=d.get("expires_at"),
            vless_uri=str(d.get("vless_uri", "")),
            order_id=str(d.get("order_id", "")),
            created=bool(d.get("created", False)),
            duration_days=int(d.get("duration_days", 0)),
        )

    async def add_subscription(
        self, payload: AddSubscriptionRequest | dict[str, Any]
    ) -> AddSubscriptionFullResponse:
        """POST /api/v1/subscriptions/add."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "POST", "/api/v1/subscriptions/add", json=data, unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected add_subscription response: {out}")
        connections_raw = out.get("connections", [])
        connections = [
            self._dict_to_add_subscription_response(c)
            for c in connections_raw
            if isinstance(c, dict)
        ]
        if not connections:
            connections = [self._dict_to_add_subscription_response(out)]
        return AddSubscriptionFullResponse(
            order_id=str(out.get("order_id", "")),
            subscription_url=str(out.get("subscription_url", "")),
            duration_days=int(out.get("duration_days", 0)),
            expires_at=out.get("expires_at"),
            connections=connections,
        )

    def _dict_to_renew_subscription_response(self, d: dict[str, Any]) -> RenewSubscriptionResponse:
        return RenewSubscriptionResponse(
            server_name=str(d.get("server_name", "")),
            client_uuid=str(d.get("client_uuid", "")),
            email=str(d.get("email", "")),
            inbound_id=int(d.get("inbound_id", 0)),
            inbound_remark=str(d.get("inbound_remark", "")),
            host=str(d.get("host", "")),
            port=int(d.get("port", 0)),
            total_gb=int(d.get("total_gb", 0)),
            limit_ip=int(d.get("limit_ip", 0)),
            expires_at=d.get("expires_at"),
            vless_uri=str(d.get("vless_uri", "")),
            renewed=bool(d.get("renewed", False)),
            duration_days_added=int(d.get("duration_days_added", 0)),
            duration_days_total=int(d.get("duration_days_total", 0)),
        )

    async def renew_subscription(
        self, payload: RenewSubscriptionRequest | dict[str, Any]
    ) -> RenewSubscriptionResponse:
        """POST /api/v1/subscriptions/renew."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "POST", "/api/v1/subscriptions/renew", json=data, unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected renew_subscription response: {out}")
        return self._dict_to_renew_subscription_response(out)

    def _dict_to_delete_subscription_response(
        self, d: dict[str, Any]
    ) -> DeleteSubscriptionResponse:
        return DeleteSubscriptionResponse(
            deleted=bool(d.get("deleted", False)),
            server_name=str(d.get("server_name", "")),
            client_uuid=str(d.get("client_uuid", "")),
            email=str(d.get("email", "")),
            inbound_id=int(d.get("inbound_id", 0)),
        )

    async def delete_subscription(
        self, payload: DeleteSubscriptionRequest | dict[str, Any]
    ) -> DeleteSubscriptionResponse:
        """POST /api/v1/subscriptions/delete."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "POST", "/api/v1/subscriptions/delete", json=data, unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected delete_subscription response: {out}")
        return self._dict_to_delete_subscription_response(out)

    def _dict_to_user_response(self, d: dict[str, Any]) -> UserResponse:
        return UserResponse(
            id=int(d.get("id", 0)),
            tg_id=int(d.get("tg_id", 0)),
            username=d.get("username"),
            first_name=d.get("first_name"),
            language=str(d.get("language", "en")),
            created_at=d.get("created_at"),
        )

    async def register_user(self, payload: UserCreate | dict[str, Any]) -> UserResponse:
        """POST /api/v1/users/register."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "POST", "/api/v1/users/register", json=data, unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected register_user response: {out}")
        return self._dict_to_user_response(out)

    def _dict_to_plan_response(self, d: dict[str, Any]) -> PlanResponse:
        return PlanResponse(
            id=int(d.get("id", 0)),
            name=str(d.get("name", "")),
            duration_days=int(d.get("duration_days", 0)),
            price_usd=float(d.get("price_usd", 0)),
            device_limit=int(d.get("device_limit", 0)),
            data_limit_gb=int(d.get("data_limit_gb", 0)),
        )

    async def list_plans(self) -> list[PlanResponse]:
        """GET /api/v1/plans."""
        out = await self._request("GET", "/api/v1/plans", unwrap_result=False)
        if not isinstance(out, list):
            return []
        return [self._dict_to_plan_response(item) for item in out if isinstance(item, dict)]

    def _dict_to_server_response(self, d: dict[str, Any]) -> ServerResponse:
        return ServerResponse(
            id=int(d.get("id", 0)),
            name=str(d.get("name", "")),
            country=str(d.get("country", "")),
            ip_address=str(d.get("ip_address", "")),
            ram=d.get("ram"),
            cpu=d.get("cpu"),
            disk=d.get("disk"),
            status=str(d.get("status", "")),
            weight=int(d.get("weight", 1)),
            enabled=bool(d.get("enabled", True)),
            created_at=d.get("created_at"),
        )

    async def list_servers_v1(self) -> list[ServerResponse]:
        """GET /api/v1/servers."""
        out = await self._request("GET", "/api/v1/servers", unwrap_result=False)
        if not isinstance(out, list):
            return []
        return [self._dict_to_server_response(item) for item in out if isinstance(item, dict)]

    async def create_server(
        self, payload: ServerCreate | dict[str, Any]
    ) -> ServerResponse:
        """POST /api/v1/servers."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "POST", "/api/v1/servers", json=data, unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected create_server response: {out}")
        return self._dict_to_server_response(out)

    async def delete_server(self, server_id: int) -> None:
        """DELETE /api/v1/servers/{server_id}."""
        await self._request("DELETE", f"/api/v1/servers/{server_id}", unwrap_result=False)

    def _dict_to_connection_response(self, d: dict[str, Any]) -> ConnectionResponse:
        return ConnectionResponse(
            id=int(d.get("id", 0)),
            user_id=int(d.get("user_id", 0)),
            server_id=int(d.get("server_id", 0)),
            order_id=int(d.get("order_id", 0)),
            server_name=str(d.get("server_name", "")),
            protocol=str(d.get("protocol", "")),
            client_uuid=str(d.get("client_uuid", "")),
            inbound_id=int(d.get("inbound_id", 0)),
            total_gb=int(d.get("total_gb", 0)),
            limit_ip=int(d.get("limit_ip", 0)),
            created_at=str(d.get("created_at", "")),
            expires_at=str(d.get("expires_at", "")),
            country=d.get("country"),
            vless_uri=d.get("vless_uri"),
        )

    async def add_connection(
        self, payload: ConnectionCreate | dict[str, Any]
    ) -> SubscriptionCreateResponse:
        """POST /api/v1/connections."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "POST", "/api/v1/connections", json=data, unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected add_connection response: {out}")
        conns = out.get("connections") or []
        return SubscriptionCreateResponse(
            order_id=int(out.get("order_id", 0)),
            duration_days=int(out.get("duration_days", 0)),
            expires_at=str(out.get("expires_at", "")),
            connections=[
                self._dict_to_connection_response(c) for c in conns if isinstance(c, dict)
            ],
        )

    async def list_connections(
        self,
        user_id: Optional[int] = None,
        tg_id: Optional[int] = None,
    ) -> list[ConnectionResponse]:
        """GET /api/v1/connections?user_id=...&tg_id=..."""
        params: list[str] = []
        if user_id is not None:
            params.append(f"user_id={user_id}")
        if tg_id is not None:
            params.append(f"tg_id={tg_id}")
        path = "/api/v1/connections" + ("?" + "&".join(params) if params else "")
        out = await self._request("GET", path, unwrap_result=False)
        if not isinstance(out, list):
            return []
        return [
            self._dict_to_connection_response(item) for item in out if isinstance(item, dict)
        ]

    async def connection_stats(self) -> ConnectionStatsResponse:
        """GET /api/v1/connections/stats."""
        out = await self._request("GET", "/api/v1/connections/stats", unwrap_result=False)
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected connection_stats response: {out}")
        return ConnectionStatsResponse(
            total_connections=int(out.get("total_connections", 0)),
            active_connections=int(out.get("active_connections", 0)),
            by_country=out.get("by_country") or [],
            top_users_by_connections=out.get("top_users_by_connections") or [],
        )

    async def get_connection(self, connection_id: int) -> ConnectionResponse:
        """GET /api/v1/connections/{connection_id}."""
        out = await self._request(
            "GET", f"/api/v1/connections/{connection_id}", unwrap_result=False
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected get_connection response: {out}")
        return self._dict_to_connection_response(out)

    async def update_connection(
        self,
        connection_id: int,
        payload: ConnectionUpdate | dict[str, Any],
    ) -> ConnectionResponse:
        """PATCH /api/v1/connections/{connection_id}."""
        data = _to_dict(payload) if not isinstance(payload, dict) else payload
        out = await self._request(
            "PATCH",
            f"/api/v1/connections/{connection_id}",
            json=data,
            unwrap_result=False,
        )
        if not isinstance(out, dict):
            raise MasterNodeError(f"Unexpected update_connection response: {out}")
        return self._dict_to_connection_response(out)

    async def delete_connection(self, connection_id: int) -> None:
        """DELETE /api/v1/connections/{connection_id}."""
        await self._request(
            "DELETE", f"/api/v1/connections/{connection_id}", unwrap_result=False
        )


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert dataclass or object to dict for JSON."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return dict(obj.__dict__)
    raise ValueError(f"Cannot convert to dict: {type(obj)}")
