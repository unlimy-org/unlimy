from __future__ import annotations

from dataclasses import dataclass

from app.db.repository import OrderData, ProvisioningJob, Repository


@dataclass
class ProvisioningResult:
    job_id: int
    slave_node: str
    status: str


class ProvisioningService:
    """Master-node stub orchestrator for slave-node config generation."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    async def enqueue_after_payment(self, order: OrderData) -> ProvisioningResult:
        slave_node = self._pick_slave_node(order.server)
        job: ProvisioningJob = await self.repo.create_or_get_provisioning_job(
            order_id=order.id,
            tg_id=order.tg_id,
            server=order.server,
            protocol=order.protocol,
            slave_node=slave_node,
            status="queued",
            notes="stub_master_to_slave_dispatch",
        )
        return ProvisioningResult(
            job_id=job.id,
            slave_node=job.slave_node,
            status=job.status,
        )

    @staticmethod
    def _pick_slave_node(server: str) -> str:
        mapping = {
            "de": "slave-de-01",
            "fi": "slave-fi-01",
            "no": "slave-no-01",
            "nl": "slave-nl-01",
        }
        return mapping.get(server, "slave-generic-01")
