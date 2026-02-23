from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Task:
    task_id: str
    status: str
    message: str
    config_text: str | None
    created_at: float


TASKS: dict[str, Task] = {}
TASKS_LOCK = threading.Lock()


MOCK_HOST = os.getenv("MOCK_MASTER_HOST", "127.0.0.1")
MOCK_PORT = int(os.getenv("MOCK_MASTER_PORT", "6767"))
MOCK_TASK_DELAY_SEC = int(os.getenv("MOCK_TASK_DELAY_SEC", "5"))
MOCK_FAIL_RATE = float(os.getenv("MOCK_FAIL_RATE", "0"))  # 0..1


def _servers_payload() -> dict[str, Any]:
    # Mirrors expected shape used by MasterNodeClient.
    return {
        "servers": [
            {"server_id": "DE-1", "country": "de", "ping_ms": 20, "status": "up", "white_ip": "10.0.0.11", "stats": "RAM 2G / CPU 20%"},
            {"server_id": "DE-2", "country": "de", "ping_ms": 40, "status": "up", "white_ip": "10.0.0.12", "stats": "RAM 2G / CPU 25%"},
            {"server_id": "FI-1", "country": "fi", "ping_ms": 900, "status": "up", "white_ip": "10.0.1.11", "stats": "RAM 1G / CPU 30%"},
            {"server_id": "NO-1", "country": "no", "ping_ms": 65, "status": "up", "white_ip": "10.0.2.11", "stats": "RAM 2G / CPU 18%"},
            {"server_id": "NL-1", "country": "nl", "ping_ms": 55, "status": "up", "white_ip": "10.0.3.11", "stats": "RAM 2G / CPU 22%"},
        ]
    }


def _schedule_task_finish(task_id: str, payload: dict[str, Any], renew: bool = False) -> None:
    def _finish() -> None:
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if not task:
                return

            if MOCK_FAIL_RATE > 0 and (uuid.uuid4().int % 1000) < int(MOCK_FAIL_RATE * 1000):
                task.status = "failed"
                task.message = "Mock generation failed"
                task.config_text = None
                return

            server_id = str(payload.get("server_id") or "DE-1")
            protocol = str(payload.get("protocol") or "wireguard")
            tg_id = str(payload.get("tg_id") or "0")
            order_id = str(payload.get("order_id") or payload.get("renew_of") or "0")
            tag = "renew" if renew else "new"
            task.status = "done"
            task.message = "Config generated"
            task.config_text = (
                f"# MOCK VPN CONFIG ({tag})\n"
                f"task_id={task_id}\n"
                f"tg_id={tg_id}\n"
                f"order_or_source={order_id}\n"
                f"server={server_id}\n"
                f"protocol={protocol}\n"
                f"generated_at={int(time.time())}\n"
                f"token={uuid.uuid4().hex[:24]}\n"
            )

    timer = threading.Timer(MOCK_TASK_DELAY_SEC, _finish)
    timer.daemon = True
    timer.start()


class Handler(BaseHTTPRequestHandler):
    server_version = "MockMasterNode/0.1"

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"ok": True, "result": {"status": "up"}})
            return

        if self.path == "/servers":
            self._send(HTTPStatus.OK, {"ok": True, "result": _servers_payload()})
            return

        if self.path.startswith("/tasks/"):
            task_id = self.path.split("/tasks/", 1)[1].strip()
            with TASKS_LOCK:
                task = TASKS.get(task_id)
            if not task:
                self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "task_not_found"})
                return
            self._send(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "result": {
                        "task_id": task.task_id,
                        "status": task.status,
                        "message": task.message,
                        "config": task.config_text,
                    },
                },
            )
            return

        self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/configs/create":
            payload = self._read_json()
            task_id = uuid.uuid4().hex[:16]
            task = Task(
                task_id=task_id,
                status="pending",
                message="Task accepted",
                config_text=None,
                created_at=time.time(),
            )
            with TASKS_LOCK:
                TASKS[task_id] = task
            _schedule_task_finish(task_id, payload, renew=False)
            self._send(HTTPStatus.OK, {"ok": True, "result": {"task_id": task_id}})
            return

        if self.path == "/configs/renew":
            payload = self._read_json()
            task_id = uuid.uuid4().hex[:16]
            task = Task(
                task_id=task_id,
                status="pending",
                message="Renew task accepted",
                config_text=None,
                created_at=time.time(),
            )
            with TASKS_LOCK:
                TASKS[task_id] = task
            _schedule_task_finish(task_id, payload, renew=True)
            self._send(HTTPStatus.OK, {"ok": True, "result": {"task_id": task_id}})
            return

        self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def log_message(self, fmt: str, *args: Any) -> None:  # suppress noisy default logs
        return


def main() -> None:
    server = ThreadingHTTPServer((MOCK_HOST, MOCK_PORT), Handler)
    print(f"[mock-master-node] listening on http://{MOCK_HOST}:{MOCK_PORT}")
    print(f"[mock-master-node] task delay: {MOCK_TASK_DELAY_SEC}s, fail rate: {MOCK_FAIL_RATE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
