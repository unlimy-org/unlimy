"""
Repository for VPN gateway schema: users, plans, servers, orders, connections, payments, settings.
Draft and user state stored in settings (JSON). last_bot_message_id in settings per tg_id.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import (
    Connection as ConnectionModel,
    Order as OrderModel,
    Payment as PaymentModel,
    Plan as PlanModel,
    Server as ServerModel,
    Setting as SettingModel,
    SupportTicket as SupportTicketModel,
    SupportTicketMessage as SupportTicketMessageModel,
    User as UserModel,
)
from app.db.session import _engine, close_db, get_session, init_db


@dataclass
class UserData:
    tg_id: int
    language: str
    username: str
    name: str
    last_bot_message_id: Optional[int]


@dataclass
class DraftOrder:
    plan: Optional[str]  # plan code e.g. "standard_12"
    server: Optional[str]  # server name
    protocol: Optional[str]
    payment: Optional[str]


@dataclass
class OrderData:
    id: int
    tg_id: int
    plan: str  # plan name/code for display
    server: str  # server name for display
    protocol: str
    payment_method: str
    amount_usd: str
    status: str
    plan_id: int = 0
    server_id: Optional[int] = None


@dataclass
class ServerData:
    server_id: str  # server name
    white_ip: str
    server_pwd: str
    country: str
    ssh_key: str
    create_date: str
    status: str
    stats: str
    ping_ms: int


@dataclass
class ConnectionData:
    id: int
    tg_id: int
    server_id: str  # server name for display
    protocol: str
    create_date: str
    speed_limits: str
    devices_limits: str
    data_limits: str
    config_text: str  # vless_uri or config content
    expiration_date: str
    status: str
    task_id: Optional[str] = None


@dataclass
class SupportTicketData:
    id: int
    tg_id: int
    status: str
    created_at: str
    updated_at: str


@dataclass
class SupportTicketMessageData:
    id: int
    ticket_id: int
    sender_tg_id: int
    body: str
    is_admin: bool
    created_at: str


def _settings_key_draft(tg_id: int) -> str:
    return f"draft:{tg_id}"


def _settings_key_state(tg_id: int) -> str:
    return f"user_state:{tg_id}"


def _settings_key_last_msg(tg_id: int) -> str:
    return f"last_bot_message_id:{tg_id}"


class Repository:
    def __init__(self) -> None:
        pass

    _READY_PLAN_NAMES = {"entry", "standard", "premium", "family", "business_start"}

    @staticmethod
    def _reconstruct_plan_code(
        plan_name: str, months: int, *, server: str = "", protocol: str = ""
    ) -> str:
        """Reconstruct the plan code format that _offer_from_plan understands."""
        if plan_name in Repository._READY_PLAN_NAMES:
            return f"ready:{plan_name}:{months}"
        if plan_name == "custom" and server and protocol:
            return f"custom:{server}:{protocol}:{months}:1"
        return f"ready:{plan_name}:{months}"

    @staticmethod
    def _parse_draft_plan_code(plan_code: str) -> tuple[str, int, int]:
        """Parse plan code into (plan_name, months, devices).

        Formats:
          ready:entry:1        → ("entry", 1, 1)
          custom:srv:proto:3:5 → ("custom", 3, 5)
          standard_12m         → ("standard", 12, 1)
          standard_12          → ("standard", 12, 1)
          anything_else        → (plan_code, 1, 1)
        """
        if plan_code.startswith("ready:"):
            parts = plan_code.split(":")
            if len(parts) == 3:
                try:
                    return parts[1], int(parts[2]), 1
                except ValueError:
                    pass
            return parts[1] if len(parts) > 1 else plan_code, 1, 1

        if plan_code.startswith("custom:"):
            parts = plan_code.split(":")
            if len(parts) == 5:
                try:
                    return "custom", int(parts[3]), int(parts[4])
                except ValueError:
                    pass
            return "custom", 1, 1

        if "_" in plan_code and plan_code.split("_")[-1].replace("m", "").isdigit():
            name, tail = plan_code.rsplit("_", 1)
            try:
                return name, int(tail.replace("m", "")), 1
            except ValueError:
                pass

        return plan_code, 1, 1

    @classmethod
    async def create(cls, dsn: str) -> "Repository":
        await init_db(dsn)
        repo = cls()
        await repo._migrate()
        return repo

    async def _migrate(self) -> None:
        from pathlib import Path

        from app.db.session import _engine as engine

        if engine is None:
            raise RuntimeError("Database not initialized")

        migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
        for mig_file in sorted(migrations_dir.glob("*.sql")):
            sql = mig_file.read_text(encoding="utf-8")
            async with engine.connect() as conn:
                await conn.execute(text(sql))
                await conn.commit()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def ensure_user(
        self, tg_id: int, language: str, username: str = "", name: str = ""
    ) -> UserData:
        async with get_session() as session:
            stmt = (
                pg_insert(UserModel)
                .values(tg_id=tg_id, username=username, first_name=name, language=language)
                .on_conflict_do_update(
                    index_elements=[UserModel.tg_id],
                    set_={
                        "username": username,
                        "first_name": name,
                        "language": language,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()
        user = await self.get_user(tg_id)
        assert user is not None
        return user

    async def get_user(self, tg_id: int) -> Optional[UserData]:
        async with get_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.tg_id == tg_id)
            )
            row = result.scalars().first()
        if not row:
            return None
        last_msg = await self.get_config_value(_settings_key_last_msg(tg_id))
        return UserData(
            tg_id=row.tg_id,
            language=row.language or "en",
            username=row.username or "",
            name=row.first_name or "",
            last_bot_message_id=int(last_msg) if last_msg and last_msg.isdigit() else None,
        )

    async def _get_user_id(self, tg_id: int) -> Optional[str]:
        async with get_session() as session:
            result = await session.execute(
                select(UserModel.id).where(UserModel.tg_id == tg_id)
            )
            uid = result.scalar_one_or_none()
        return str(uid) if uid is not None else None

    async def set_language(self, tg_id: int, language: str) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.tg_id == tg_id)
            )
            user = result.scalars().first()
            if user:
                user.language = language
                await session.commit()

    async def set_last_bot_message_id(self, tg_id: int, message_id: Optional[int]) -> None:
        key = _settings_key_last_msg(tg_id)
        if message_id is None:
            await self.set_config_value(key, "")
        else:
            await self.set_config_value(key, str(message_id))

    # ------------------------------------------------------------------
    # Draft order (stored in settings as JSON)
    # ------------------------------------------------------------------

    async def upsert_draft(self, tg_id: int, **fields: Optional[str]) -> None:
        draft = await self.get_draft(tg_id)
        plan = fields.get("plan") if "plan" in fields else draft.plan
        server = fields.get("server") if "server" in fields else draft.server
        protocol = fields.get("protocol") if "protocol" in fields else draft.protocol
        payment = fields.get("payment") if "payment" in fields else draft.payment
        payload = json.dumps({"plan": plan, "server": server, "protocol": protocol, "payment": payment})
        await self.set_config_value(_settings_key_draft(tg_id), payload)

    async def get_draft(self, tg_id: int) -> DraftOrder:
        raw = await self.get_config_value(_settings_key_draft(tg_id))
        if not raw:
            return DraftOrder(plan=None, server=None, protocol=None, payment=None)
        try:
            d = json.loads(raw)
            return DraftOrder(
                plan=d.get("plan"),
                server=d.get("server"),
                protocol=d.get("protocol"),
                payment=d.get("payment"),
            )
        except (json.JSONDecodeError, TypeError):
            return DraftOrder(plan=None, server=None, protocol=None, payment=None)

    async def reset_draft(self, tg_id: int) -> None:
        await self.set_config_value(_settings_key_draft(tg_id), "")

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------

    async def get_plan_id_by_name_duration(self, name: str, duration_days: int) -> Optional[int]:
        async with get_session() as session:
            result = await session.execute(
                select(PlanModel.id).where(
                    PlanModel.name == name,
                    PlanModel.duration_days == duration_days,
                )
            )
            pid = result.scalar_one_or_none()
        return int(pid) if pid is not None else None

    async def get_or_create_plan(
        self, name: str, duration_days: int, price_usd: float = 0, device_limit: int = 1
    ) -> int:
        pid = await self.get_plan_id_by_name_duration(name, duration_days)
        if pid is not None:
            return pid
        async with get_session() as session:
            stmt = (
                pg_insert(PlanModel)
                .values(
                    name=name,
                    duration_days=duration_days,
                    price_usd=price_usd,
                    device_limit=device_limit,
                )
                .on_conflict_do_update(
                    index_elements=[PlanModel.name, PlanModel.duration_days],
                    set_={"price_usd": price_usd},
                )
                .returning(PlanModel.id)
            )
            result = await session.execute(stmt)
            new_id = result.scalar_one_or_none()
            await session.commit()
        if new_id is None:
            new_id = await self.get_plan_id_by_name_duration(name, duration_days)
        return int(new_id or 1)

    # ------------------------------------------------------------------
    # Servers
    # ------------------------------------------------------------------

    async def get_server_id_by_name(self, name: str) -> Optional[int]:
        async with get_session() as session:
            result = await session.execute(
                select(ServerModel.id).where(ServerModel.name == name)
            )
            sid = result.scalar_one_or_none()
        return int(sid) if sid is not None else None

    async def upsert_server_data(self, server: ServerData) -> None:
        async with get_session() as session:
            stmt = (
                pg_insert(ServerModel)
                .values(
                    name=server.server_id,
                    country=server.country,
                    ip_address=server.white_ip or "0.0.0.0",
                    status=server.status or "active",
                    base_url="https://" + (server.white_ip or "localhost"),
                    username="admin",
                    password=server.server_pwd or "",
                )
                .on_conflict_do_update(
                    index_elements=[ServerModel.name],
                    set_={
                        "ip_address": server.white_ip or "0.0.0.0",
                        "country": server.country,
                        "status": server.status or "active",
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def list_servers_by_country(self, country: str) -> list[ServerData]:
        async with get_session() as session:
            result = await session.execute(
                select(ServerModel)
                .where(
                    func.lower(ServerModel.country) == country.lower(),
                    ServerModel.enabled == True,  # noqa: E712
                )
                .order_by(ServerModel.name.asc())
            )
            rows = result.scalars().all()
        return [
            ServerData(
                server_id=row.name,
                white_ip=row.ip_address,
                server_pwd="",
                country=row.country,
                ssh_key="",
                create_date="",
                status=row.status,
                stats="",
                ping_ms=0,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def create_order_from_draft(self, tg_id: int, amount_usd: str) -> Optional[int]:
        draft = await self.get_draft(tg_id)
        if not draft.plan or not draft.server or not draft.protocol or not draft.payment:
            return None

        plan_name, months, devices = self._parse_draft_plan_code(draft.plan)
        duration_days = 30 * max(months, 1)
        amount = float(amount_usd) if amount_usd else 0
        plan_id = await self.get_plan_id_by_name_duration(plan_name, duration_days)
        if not plan_id:
            plan_id = await self.get_plan_id_by_name_duration(plan_name, 30)
        if not plan_id:
            plan_id = await self.get_or_create_plan(plan_name, duration_days, amount, devices)
        server_id = await self.get_server_id_by_name(draft.server)
        if not plan_id:
            return None
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return None
        async with get_session() as session:
            order = OrderModel(
                user_id=user_id,
                plan_id=plan_id,
                server_id=server_id,
                protocol=draft.protocol or "vless",
                amount_usd=amount,
                status="pending",
                payment_method=draft.payment or "stars",
            )
            session.add(order)
            await session.flush()
            order_id = order.id
            await session.commit()
        return int(order_id) if order_id else None

    async def get_order(self, order_id: int, tg_id: int) -> Optional[OrderData]:
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return None
        async with get_session() as session:
            result = await session.execute(
                select(
                    OrderModel.id,
                    OrderModel.user_id,
                    OrderModel.plan_id,
                    OrderModel.server_id,
                    OrderModel.protocol,
                    OrderModel.amount_usd,
                    OrderModel.status,
                    OrderModel.payment_method,
                    PlanModel.name.label("plan_name"),
                    PlanModel.duration_days,
                    ServerModel.name.label("server_name"),
                )
                .outerjoin(PlanModel, PlanModel.id == OrderModel.plan_id)
                .outerjoin(ServerModel, ServerModel.id == OrderModel.server_id)
                .where(OrderModel.id == order_id, OrderModel.user_id == user_id)
            )
            row = result.first()
        if not row:
            return None
        plan_name = row.plan_name or str(row.plan_id)
        duration_days = row.duration_days or 30
        months = max(1, duration_days // 30)
        plan_code = self._reconstruct_plan_code(
            plan_name,
            months,
            server=row.server_name or str(row.server_id or ""),
            protocol=row.protocol or "vless",
        )
        return OrderData(
            id=row.id,
            tg_id=tg_id,
            plan=plan_code,
            server=row.server_name or str(row.server_id or ""),
            protocol=row.protocol or "vless",
            payment_method=row.payment_method or "stars",
            amount_usd=str(row.amount_usd),
            status=row.status,
            plan_id=row.plan_id,
            server_id=row.server_id,
        )

    async def list_orders_for_user(self, tg_id: int, limit: int = 10) -> list[OrderData]:
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return []
        async with get_session() as session:
            result = await session.execute(
                select(
                    OrderModel.id,
                    OrderModel.plan_id,
                    OrderModel.server_id,
                    OrderModel.protocol,
                    OrderModel.amount_usd,
                    OrderModel.status,
                    OrderModel.payment_method,
                    PlanModel.name.label("plan_name"),
                    PlanModel.duration_days,
                    ServerModel.name.label("server_name"),
                )
                .outerjoin(PlanModel, PlanModel.id == OrderModel.plan_id)
                .outerjoin(ServerModel, ServerModel.id == OrderModel.server_id)
                .where(OrderModel.user_id == user_id)
                .order_by(OrderModel.id.desc())
                .limit(limit)
            )
            rows = result.all()
        out: list[OrderData] = []
        for r in rows:
            plan_name = r.plan_name or str(r.plan_id)
            duration_days = r.duration_days or 30
            months = max(1, duration_days // 30)
            server = r.server_name or str(r.server_id or "")
            protocol = r.protocol or "vless"
            plan_code = self._reconstruct_plan_code(plan_name, months, server=server, protocol=protocol)
            out.append(
                OrderData(
                    id=r.id,
                    tg_id=tg_id,
                    plan=plan_code,
                    server=server,
                    protocol=protocol,
                    payment_method=r.payment_method or "stars",
                    amount_usd=str(r.amount_usd),
                    status=r.status,
                    plan_id=r.plan_id,
                    server_id=r.server_id,
                )
            )
        return out

    async def update_order_status(
        self,
        order_id: int,
        tg_id: int,
        status: str,
        failure_reason: Optional[str] = None,
    ) -> bool:
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return False
        async with get_session() as session:
            result = await session.execute(
                select(OrderModel).where(
                    OrderModel.id == order_id,
                    OrderModel.user_id == user_id,
                )
            )
            order = result.scalars().first()
            if not order:
                return False
            order.status = status
            order.updated_at = datetime.now(timezone.utc)
            await session.commit()
        return True

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def log_payment_event(
        self,
        order_id: int,
        tg_id: int,
        payment_method: str,
        event_type: str,
        details: Optional[str] = None,
    ) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(OrderModel.amount_usd).where(OrderModel.id == order_id)
            )
            amount_row = result.scalar_one_or_none()
            amount = float(amount_row) if amount_row else 0
            payment = PaymentModel(
                order_id=order_id,
                provider=payment_method,
                amount_usd=amount,
                status="succeeded" if event_type == "succeeded" else "pending",
            )
            session.add(payment)
            await session.commit()

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    async def create_connection(
        self,
        tg_id: int,
        server_id: str,
        protocol: str,
        speed_limits: str,
        devices_limits: str,
        data_limits: str,
        expiration_date: str,
        status: str = "pending",
        task_id: Optional[str] = None,
        order_id: Optional[int] = None,
        *,
        user_id: Optional[str] = None,
        server_id_int: Optional[int] = None,
        client_uuid: str = "",
        inbound_id: int = 0,
        total_gb: int = 0,
        limit_ip: int = 0,
        vless_uri: Optional[str] = None,
    ) -> int:
        uid = user_id or await self._get_user_id(tg_id)
        if not uid:
            raise ValueError("user not found")
        sid = server_id_int or await self.get_server_id_by_name(server_id)
        if not sid and order_id:
            async with get_session() as session:
                result = await session.execute(
                    select(OrderModel.server_id).where(OrderModel.id == order_id)
                )
                ord_sid = result.scalar_one_or_none()
                if ord_sid:
                    sid = ord_sid
        if not sid:
            sid = 1
        if not order_id:
            raise ValueError("order_id required")

        exp_dt = (
            datetime.fromisoformat(expiration_date)
            if isinstance(expiration_date, str)
            else expiration_date
        )

        async with get_session() as session:
            conn_obj = ConnectionModel(
                user_id=uid,
                server_id=sid,
                order_id=order_id,
                protocol=protocol,
                client_uuid=client_uuid or "",
                inbound_id=inbound_id,
                total_gb=total_gb,
                limit_ip=limit_ip,
                vless_uri=vless_uri,
                expires_at=exp_dt,
            )
            session.add(conn_obj)
            await session.flush()
            new_id = conn_obj.id
            await session.commit()
        return int(new_id)

    async def update_connection_task(
        self,
        connection_id: int,
        tg_id: int,
        status: str,
        task_id: Optional[str] = None,
        config_text: Optional[str] = None,
    ) -> bool:
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return False
        async with get_session() as session:
            result = await session.execute(
                select(ConnectionModel).where(
                    ConnectionModel.id == connection_id,
                    ConnectionModel.user_id == user_id,
                )
            )
            conn_obj = result.scalars().first()
            if not conn_obj:
                return False
            if config_text is not None:
                conn_obj.vless_uri = config_text
            await session.commit()
        return True

    async def list_connections_for_user(self, tg_id: int, limit: int = 10) -> list[ConnectionData]:
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return []
        async with get_session() as session:
            result = await session.execute(
                select(
                    ConnectionModel.id,
                    ConnectionModel.server_id,
                    ConnectionModel.protocol,
                    ConnectionModel.created_at,
                    ConnectionModel.expires_at,
                    ConnectionModel.vless_uri,
                    ServerModel.name.label("server_name"),
                )
                .outerjoin(ServerModel, ServerModel.id == ConnectionModel.server_id)
                .where(ConnectionModel.user_id == user_id)
                .order_by(ConnectionModel.id.desc())
                .limit(limit)
            )
            rows = result.all()
        return [
            ConnectionData(
                id=r.id,
                tg_id=tg_id,
                server_id=r.server_name or str(r.server_id),
                protocol=r.protocol or "vless",
                create_date=r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at),
                speed_limits="",
                devices_limits="",
                data_limits="",
                config_text=r.vless_uri or "",
                expiration_date=r.expires_at.isoformat() if hasattr(r.expires_at, "isoformat") else str(r.expires_at),
                status="active",
                task_id=None,
            )
            for r in rows
        ]

    async def get_connection(self, connection_id: int, tg_id: int) -> Optional[ConnectionData]:
        user_id = await self._get_user_id(tg_id)
        if not user_id:
            return None
        async with get_session() as session:
            result = await session.execute(
                select(
                    ConnectionModel.id,
                    ConnectionModel.server_id,
                    ConnectionModel.protocol,
                    ConnectionModel.created_at,
                    ConnectionModel.expires_at,
                    ConnectionModel.vless_uri,
                    ServerModel.name.label("server_name"),
                )
                .outerjoin(ServerModel, ServerModel.id == ConnectionModel.server_id)
                .where(
                    ConnectionModel.id == connection_id,
                    ConnectionModel.user_id == user_id,
                )
            )
            row = result.first()
        if not row:
            return None
        return ConnectionData(
            id=row.id,
            tg_id=tg_id,
            server_id=row.server_name or str(row.server_id),
            protocol=row.protocol or "vless",
            create_date=row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
            speed_limits="",
            devices_limits="",
            data_limits="",
            config_text=row.vless_uri or "",
            expiration_date=row.expires_at.isoformat() if hasattr(row.expires_at, "isoformat") else str(row.expires_at),
            status="active",
            task_id=None,
        )

    # ------------------------------------------------------------------
    # Settings (key-value)
    # ------------------------------------------------------------------

    async def set_config_value(self, key: str, value: str) -> None:
        async with get_session() as session:
            stmt = (
                pg_insert(SettingModel)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=[SettingModel.key],
                    set_={"value": value},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def get_config_value(self, key: str) -> Optional[str]:
        async with get_session() as session:
            result = await session.execute(
                select(SettingModel.value).where(SettingModel.key == key)
            )
            return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # User state (stored in settings as JSON)
    # ------------------------------------------------------------------

    async def set_user_state(self, tg_id: int, state: str, payload: Optional[str] = None) -> None:
        await self.set_config_value(
            _settings_key_state(tg_id),
            json.dumps({"state": state, "payload": payload or ""}),
        )

    async def get_user_state(self, tg_id: int) -> tuple[Optional[str], Optional[str]]:
        raw = await self.get_config_value(_settings_key_state(tg_id))
        if not raw:
            return None, None
        try:
            d = json.loads(raw)
            return d.get("state"), d.get("payload") or None
        except (json.JSONDecodeError, TypeError):
            return None, None

    async def clear_user_state(self, tg_id: int) -> None:
        await self.set_config_value(_settings_key_state(tg_id), "")

    # ------------------------------------------------------------------
    # Support tickets
    # ------------------------------------------------------------------

    async def create_support_ticket(self, tg_id: int, body: str) -> int:
        async with get_session() as session:
            ticket = SupportTicketModel(tg_id=tg_id, status="open")
            session.add(ticket)
            await session.flush()
            msg = SupportTicketMessageModel(
                ticket_id=ticket.id,
                sender_tg_id=tg_id,
                body=body,
                is_admin=False,
            )
            session.add(msg)
            await session.commit()
            return int(ticket.id)

    async def add_support_ticket_message(
        self, ticket_id: int, sender_tg_id: int, body: str, is_admin: bool
    ) -> int:
        async with get_session() as session:
            msg = SupportTicketMessageModel(
                ticket_id=ticket_id,
                sender_tg_id=sender_tg_id,
                body=body,
                is_admin=is_admin,
            )
            session.add(msg)
            await session.flush()
            msg_id = msg.id

            result = await session.execute(
                select(SupportTicketModel).where(SupportTicketModel.id == ticket_id)
            )
            ticket = result.scalars().first()
            if ticket:
                ticket.updated_at = datetime.now(timezone.utc)
            await session.commit()
        return int(msg_id)

    async def update_support_ticket_status(self, ticket_id: int, status: str) -> bool:
        async with get_session() as session:
            result = await session.execute(
                select(SupportTicketModel).where(SupportTicketModel.id == ticket_id)
            )
            ticket = result.scalars().first()
            if not ticket:
                return False
            ticket.status = status
            ticket.updated_at = datetime.now(timezone.utc)
            await session.commit()
        return True

    async def get_support_ticket(self, ticket_id: int) -> Optional[SupportTicketData]:
        async with get_session() as session:
            result = await session.execute(
                select(SupportTicketModel).where(SupportTicketModel.id == ticket_id)
            )
            row = result.scalars().first()
        if not row:
            return None
        return SupportTicketData(
            id=row.id,
            tg_id=row.tg_id,
            status=row.status,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at),
        )

    async def get_support_ticket_for_user(
        self, ticket_id: int, tg_id: int
    ) -> Optional[SupportTicketData]:
        async with get_session() as session:
            result = await session.execute(
                select(SupportTicketModel).where(
                    SupportTicketModel.id == ticket_id,
                    SupportTicketModel.tg_id == tg_id,
                )
            )
            row = result.scalars().first()
        if not row:
            return None
        return SupportTicketData(
            id=row.id,
            tg_id=row.tg_id,
            status=row.status,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at),
        )

    async def list_support_tickets_for_user(
        self, tg_id: int, limit: int = 20
    ) -> list[SupportTicketData]:
        async with get_session() as session:
            result = await session.execute(
                select(SupportTicketModel)
                .where(SupportTicketModel.tg_id == tg_id)
                .order_by(SupportTicketModel.updated_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [
            SupportTicketData(
                id=r.id,
                tg_id=r.tg_id,
                status=r.status,
                created_at=str(r.created_at),
                updated_at=str(r.updated_at),
            )
            for r in rows
        ]

    async def list_open_support_tickets(self, limit: int = 30) -> list[SupportTicketData]:
        async with get_session() as session:
            result = await session.execute(
                select(SupportTicketModel)
                .where(SupportTicketModel.status == "open")
                .order_by(SupportTicketModel.updated_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [
            SupportTicketData(
                id=r.id,
                tg_id=r.tg_id,
                status=r.status,
                created_at=str(r.created_at),
                updated_at=str(r.updated_at),
            )
            for r in rows
        ]

    async def list_support_ticket_messages(
        self, ticket_id: int, limit: int = 30
    ) -> list[SupportTicketMessageData]:
        async with get_session() as session:
            result = await session.execute(
                select(SupportTicketMessageModel)
                .where(SupportTicketMessageModel.ticket_id == ticket_id)
                .order_by(SupportTicketMessageModel.id.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [
            SupportTicketMessageData(
                id=r.id,
                ticket_id=r.ticket_id,
                sender_tg_id=r.sender_tg_id,
                body=r.body,
                is_admin=r.is_admin,
                created_at=str(r.created_at),
            )
            for r in reversed(rows)
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await close_db()
