from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import asyncpg


@dataclass
class UserData:
    tg_id: int
    language: str
    username: str
    name: str
    last_bot_message_id: Optional[int]


@dataclass
class DraftOrder:
    plan: Optional[str]
    server: Optional[str]
    protocol: Optional[str]
    payment: Optional[str]


@dataclass
class OrderData:
    id: int
    tg_id: int
    plan: str
    server: str
    protocol: str
    payment_method: str
    amount_usd: str
    status: str


@dataclass
class ServerData:
    server_id: str
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
    server_id: str
    protocol: str
    create_date: str
    speed_limits: str
    devices_limits: str
    data_limits: str
    config_text: str
    expiration_date: str
    status: str
    task_id: Optional[str]


@dataclass
class ProvisioningJob:
    id: int
    order_id: int
    tg_id: int
    server: str
    protocol: str
    slave_node: str
    status: str
    config_stub: Optional[str]


class Repository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create(cls, dsn: str) -> "Repository":
        pool = await asyncpg.create_pool(dsn)
        repo = cls(pool)
        await repo._migrate()
        return repo

    async def _migrate(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    tg_id BIGINT PRIMARY KEY,
                    language TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '',
                    last_bot_message_id BIGINT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT NOT NULL DEFAULT '';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';")

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS draft_orders (
                    tg_id BIGINT PRIMARY KEY REFERENCES users(tg_id) ON DELETE CASCADE,
                    plan TEXT NULL,
                    server TEXT NULL,
                    protocol TEXT NULL,
                    payment TEXT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vpn_orders (
                    id BIGSERIAL PRIMARY KEY,
                    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                    plan TEXT NOT NULL,
                    server TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    amount_usd INTEGER NOT NULL,
                    amount_usd_numeric NUMERIC(10,2) NULL,
                    status TEXT NOT NULL,
                    failure_reason TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    paid_at TIMESTAMPTZ NULL
                );
                """
            )
            await conn.execute(
                "ALTER TABLE vpn_orders ADD COLUMN IF NOT EXISTS amount_usd_numeric NUMERIC(10,2) NULL;"
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_events (
                    id BIGSERIAL PRIMARY KEY,
                    order_id BIGINT NOT NULL REFERENCES vpn_orders(id) ON DELETE CASCADE,
                    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                    payment_method TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provisioning_jobs (
                    id BIGSERIAL PRIMARY KEY,
                    order_id BIGINT NOT NULL UNIQUE REFERENCES vpn_orders(id) ON DELETE CASCADE,
                    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                    server TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    slave_node TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_stub TEXT NULL,
                    notes TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS server_data (
                    server_id TEXT PRIMARY KEY,
                    white_ip TEXT NOT NULL DEFAULT '',
                    server_pwd TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL,
                    ssh_key TEXT NOT NULL DEFAULT '',
                    create_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    stats TEXT NOT NULL DEFAULT '',
                    ping_ms INTEGER NOT NULL DEFAULT 9999,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connections (
                    id BIGSERIAL PRIMARY KEY,
                    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                    order_id BIGINT NULL REFERENCES vpn_orders(id) ON DELETE SET NULL,
                    server_id TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    create_date TEXT NOT NULL,
                    speed_limits TEXT NOT NULL DEFAULT '',
                    devices_limits TEXT NOT NULL DEFAULT '',
                    data_limits TEXT NOT NULL DEFAULT '',
                    config_text TEXT NOT NULL DEFAULT '',
                    expiration_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    task_id TEXT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS config_kv (
                    id BIGSERIAL PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL
                );
                """
            )

    async def ensure_user(self, tg_id: int, language: str, username: str = "", name: str = "") -> UserData:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users(tg_id, language, username, name)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (tg_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    name = EXCLUDED.name,
                    updated_at = NOW()
                """,
                tg_id,
                language,
                username,
                name,
            )
            row = await conn.fetchrow(
                """
                SELECT tg_id, language, username, name, last_bot_message_id
                FROM users
                WHERE tg_id = $1
                """,
                tg_id,
            )
            return UserData(
                tg_id=row["tg_id"],
                language=row["language"],
                username=row["username"],
                name=row["name"],
                last_bot_message_id=row["last_bot_message_id"],
            )

    async def get_user(self, tg_id: int) -> Optional[UserData]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tg_id, language, username, name, last_bot_message_id
                FROM users
                WHERE tg_id = $1
                """,
                tg_id,
            )
        if not row:
            return None
        return UserData(
            tg_id=row["tg_id"],
            language=row["language"],
            username=row["username"],
            name=row["name"],
            last_bot_message_id=row["last_bot_message_id"],
        )

    async def set_language(self, tg_id: int, language: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET language = $2, updated_at = NOW() WHERE tg_id = $1",
                tg_id,
                language,
            )

    async def set_last_bot_message_id(self, tg_id: int, message_id: Optional[int]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_bot_message_id = $2, updated_at = NOW() WHERE tg_id = $1",
                tg_id,
                message_id,
            )

    async def upsert_draft(self, tg_id: int, **fields: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO draft_orders(tg_id, plan, server, protocol, payment)
                VALUES($1, $2, $3, $4, $5)
                ON CONFLICT (tg_id)
                DO UPDATE SET
                    plan = COALESCE($2, draft_orders.plan),
                    server = COALESCE($3, draft_orders.server),
                    protocol = COALESCE($4, draft_orders.protocol),
                    payment = COALESCE($5, draft_orders.payment),
                    updated_at = NOW()
                """,
                tg_id,
                fields.get("plan"),
                fields.get("server"),
                fields.get("protocol"),
                fields.get("payment"),
            )

    async def get_draft(self, tg_id: int) -> DraftOrder:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT plan, server, protocol, payment FROM draft_orders WHERE tg_id = $1", tg_id
            )
        if not row:
            return DraftOrder(plan=None, server=None, protocol=None, payment=None)
        return DraftOrder(
            plan=row["plan"],
            server=row["server"],
            protocol=row["protocol"],
            payment=row["payment"],
        )

    async def reset_draft(self, tg_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM draft_orders WHERE tg_id = $1", tg_id)

    async def create_order_from_draft(self, tg_id: int, amount_usd: str) -> Optional[int]:
        draft = await self.get_draft(tg_id)
        if not draft.plan or not draft.server or not draft.protocol or not draft.payment:
            return None

        async with self.pool.acquire() as conn:
            order_id = await conn.fetchval(
                """
                INSERT INTO vpn_orders(
                    tg_id, plan, server, protocol, payment_method, amount_usd, amount_usd_numeric, status
                )
                VALUES($1, $2, $3, $4, $5, $6, $7, 'pending')
                RETURNING id
                """,
                tg_id,
                draft.plan,
                draft.server,
                draft.protocol,
                draft.payment,
                int(round(float(amount_usd))),
                amount_usd,
            )
        return int(order_id)

    async def get_order(self, order_id: int, tg_id: int) -> Optional[OrderData]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id, tg_id, plan, server, protocol, payment_method,
                    COALESCE(amount_usd_numeric::text, amount_usd::text) AS amount_usd,
                    status
                FROM vpn_orders
                WHERE id = $1 AND tg_id = $2
                """,
                order_id,
                tg_id,
            )
        if not row:
            return None
        return OrderData(
            id=row["id"],
            tg_id=row["tg_id"],
            plan=row["plan"],
            server=row["server"],
            protocol=row["protocol"],
            payment_method=row["payment_method"],
            amount_usd=row["amount_usd"],
            status=row["status"],
        )

    async def list_orders_for_user(self, tg_id: int, limit: int = 10) -> list[OrderData]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, tg_id, plan, server, protocol, payment_method,
                    COALESCE(amount_usd_numeric::text, amount_usd::text) AS amount_usd,
                    status
                FROM vpn_orders
                WHERE tg_id = $1
                ORDER BY id DESC
                LIMIT $2
                """,
                tg_id,
                limit,
            )
        return [
            OrderData(
                id=row["id"],
                tg_id=row["tg_id"],
                plan=row["plan"],
                server=row["server"],
                protocol=row["protocol"],
                payment_method=row["payment_method"],
                amount_usd=row["amount_usd"],
                status=row["status"],
            )
            for row in rows
        ]

    async def update_order_status(
        self,
        order_id: int,
        tg_id: int,
        status: str,
        failure_reason: Optional[str] = None,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE vpn_orders
                SET
                    status = $3,
                    failure_reason = $4,
                    updated_at = NOW(),
                    paid_at = CASE WHEN $3 = 'paid' THEN NOW() ELSE paid_at END
                WHERE id = $1 AND tg_id = $2
                """,
                order_id,
                tg_id,
                status,
                failure_reason,
            )
        return result.endswith("1")

    async def log_payment_event(
        self,
        order_id: int,
        tg_id: int,
        payment_method: str,
        event_type: str,
        details: Optional[str] = None,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO payment_events(order_id, tg_id, payment_method, event_type, details)
                VALUES($1, $2, $3, $4, $5)
                """,
                order_id,
                tg_id,
                payment_method,
                event_type,
                details,
            )

    async def upsert_server_data(self, server: ServerData) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO server_data(
                    server_id, white_ip, server_pwd, country, ssh_key,
                    create_date, status, stats, ping_ms
                )
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (server_id) DO UPDATE SET
                    white_ip = EXCLUDED.white_ip,
                    server_pwd = EXCLUDED.server_pwd,
                    country = EXCLUDED.country,
                    ssh_key = EXCLUDED.ssh_key,
                    create_date = EXCLUDED.create_date,
                    status = EXCLUDED.status,
                    stats = EXCLUDED.stats,
                    ping_ms = EXCLUDED.ping_ms,
                    updated_at = NOW()
                """,
                server.server_id,
                server.white_ip,
                server.server_pwd,
                server.country,
                server.ssh_key,
                server.create_date,
                server.status,
                server.stats,
                server.ping_ms,
            )

    async def list_servers_by_country(self, country: str) -> list[ServerData]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT server_id, white_ip, server_pwd, country, ssh_key, create_date, status, stats, ping_ms
                FROM server_data
                WHERE country = $1
                ORDER BY ping_ms ASC, server_id ASC
                """,
                country.lower(),
            )
        return [
            ServerData(
                server_id=row["server_id"],
                white_ip=row["white_ip"],
                server_pwd=row["server_pwd"],
                country=row["country"],
                ssh_key=row["ssh_key"],
                create_date=row["create_date"],
                status=row["status"],
                stats=row["stats"],
                ping_ms=row["ping_ms"],
            )
            for row in rows
        ]

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
    ) -> int:
        async with self.pool.acquire() as conn:
            new_id = await conn.fetchval(
                """
                INSERT INTO connections(
                    tg_id, order_id, server_id, protocol, create_date,
                    speed_limits, devices_limits, data_limits, expiration_date, status, task_id
                )
                VALUES($1,$2,$3,$4,NOW()::text,$5,$6,$7,$8,$9,$10)
                RETURNING id
                """,
                tg_id,
                order_id,
                server_id,
                protocol,
                speed_limits,
                devices_limits,
                data_limits,
                expiration_date,
                status,
                task_id,
            )
        return int(new_id)

    async def update_connection_task(
        self,
        connection_id: int,
        tg_id: int,
        status: str,
        task_id: Optional[str] = None,
        config_text: Optional[str] = None,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE connections
                SET
                    status = $3,
                    task_id = COALESCE($4, task_id),
                    config_text = COALESCE($5, config_text),
                    updated_at = NOW()
                WHERE id = $1 AND tg_id = $2
                """,
                connection_id,
                tg_id,
                status,
                task_id,
                config_text,
            )
        return result.endswith("1")

    async def list_connections_for_user(self, tg_id: int, limit: int = 10) -> list[ConnectionData]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, tg_id, server_id, protocol, create_date, speed_limits,
                    devices_limits, data_limits, config_text, expiration_date, status, task_id
                FROM connections
                WHERE tg_id = $1
                ORDER BY id DESC
                LIMIT $2
                """,
                tg_id,
                limit,
            )
        return [
            ConnectionData(
                id=row["id"],
                tg_id=row["tg_id"],
                server_id=row["server_id"],
                protocol=row["protocol"],
                create_date=row["create_date"],
                speed_limits=row["speed_limits"],
                devices_limits=row["devices_limits"],
                data_limits=row["data_limits"],
                config_text=row["config_text"],
                expiration_date=row["expiration_date"],
                status=row["status"],
                task_id=row["task_id"],
            )
            for row in rows
        ]

    async def get_connection(self, connection_id: int, tg_id: int) -> Optional[ConnectionData]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id, tg_id, server_id, protocol, create_date, speed_limits,
                    devices_limits, data_limits, config_text, expiration_date, status, task_id
                FROM connections
                WHERE id = $1 AND tg_id = $2
                """,
                connection_id,
                tg_id,
            )
        if not row:
            return None
        return ConnectionData(
            id=row["id"],
            tg_id=row["tg_id"],
            server_id=row["server_id"],
            protocol=row["protocol"],
            create_date=row["create_date"],
            speed_limits=row["speed_limits"],
            devices_limits=row["devices_limits"],
            data_limits=row["data_limits"],
            config_text=row["config_text"],
            expiration_date=row["expiration_date"],
            status=row["status"],
            task_id=row["task_id"],
        )

    async def set_config_value(self, key: str, value: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO config_kv(key, value)
                VALUES($1, $2)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
                """,
                key,
                value,
            )

    async def get_config_value(self, key: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            value = await conn.fetchval("SELECT value FROM config_kv WHERE key = $1", key)
        return value

    async def create_or_get_provisioning_job(
        self,
        order_id: int,
        tg_id: int,
        server: str,
        protocol: str,
        slave_node: str,
        status: str = "queued",
        notes: Optional[str] = None,
    ) -> ProvisioningJob:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO provisioning_jobs(
                    order_id, tg_id, server, protocol, slave_node, status, notes
                )
                VALUES($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (order_id) DO NOTHING
                """,
                order_id,
                tg_id,
                server,
                protocol,
                slave_node,
                status,
                notes,
            )
            row = await conn.fetchrow(
                """
                SELECT id, order_id, tg_id, server, protocol, slave_node, status, config_stub
                FROM provisioning_jobs
                WHERE order_id = $1
                """,
                order_id,
            )
        return ProvisioningJob(
            id=row["id"],
            order_id=row["order_id"],
            tg_id=row["tg_id"],
            server=row["server"],
            protocol=row["protocol"],
            slave_node=row["slave_node"],
            status=row["status"],
            config_stub=row["config_stub"],
        )

    async def close(self) -> None:
        await self.pool.close()
