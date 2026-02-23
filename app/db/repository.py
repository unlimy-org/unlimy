from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import asyncpg


@dataclass
class UserData:
    tg_id: int
    language: str
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
    amount_usd: int
    status: str


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
                    last_bot_message_id BIGINT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
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
                    status TEXT NOT NULL,
                    failure_reason TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    paid_at TIMESTAMPTZ NULL
                );
                """
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

    async def ensure_user(self, tg_id: int, language: str) -> UserData:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users(tg_id, language)
                VALUES($1, $2)
                ON CONFLICT (tg_id) DO NOTHING
                """,
                tg_id,
                language,
            )
            row = await conn.fetchrow(
                "SELECT tg_id, language, last_bot_message_id FROM users WHERE tg_id = $1", tg_id
            )
            return UserData(
                tg_id=row["tg_id"],
                language=row["language"],
                last_bot_message_id=row["last_bot_message_id"],
            )

    async def get_user(self, tg_id: int) -> Optional[UserData]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tg_id, language, last_bot_message_id FROM users WHERE tg_id = $1", tg_id
            )
        if not row:
            return None
        return UserData(
            tg_id=row["tg_id"],
            language=row["language"],
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

    async def close(self) -> None:
        await self.pool.close()

    async def create_order_from_draft(self, tg_id: int, amount_usd: int) -> Optional[int]:
        draft = await self.get_draft(tg_id)
        if not draft.plan or not draft.server or not draft.protocol or not draft.payment:
            return None

        async with self.pool.acquire() as conn:
            order_id = await conn.fetchval(
                """
                INSERT INTO vpn_orders(
                    tg_id, plan, server, protocol, payment_method, amount_usd, status
                )
                VALUES($1, $2, $3, $4, $5, $6, 'pending')
                RETURNING id
                """,
                tg_id,
                draft.plan,
                draft.server,
                draft.protocol,
                draft.payment,
                amount_usd,
            )
        return int(order_id)

    async def get_order(self, order_id: int, tg_id: int) -> Optional[OrderData]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tg_id, plan, server, protocol, payment_method, amount_usd, status
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
