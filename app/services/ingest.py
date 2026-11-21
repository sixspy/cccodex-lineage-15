"""清洗调度入库：目录指纹与隔离窗拧了就拦住。"""
from __future__ import annotations

from app.db import get_db
from app.services import revisions as revisions_svc
from app.services.errors import ServiceError


def list_batches(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM ingest_batches ORDER BY id DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]


def ingest_batch(
    node_id: int,
    catalog_fingerprint: str = "",
    db_path: str | None = None,
) -> dict:
    provided = (catalog_fingerprint or "").strip()
    with get_db(db_path) as conn:
        node = conn.execute(
            "SELECT * FROM lineage_nodes WHERE id=?", (node_id,)
        ).fetchone()
        if not node:
            raise ServiceError("节点不存在", 404)
        windows = revisions_svc.covering_open_windows(conn, node["layer"])
        for win in windows:
            recorded = win["catalog_fingerprint"]
            live = revisions_svc.live_fingerprint(conn, win["scope"])
            if live != recorded:
                raise ServiceError(
                    f"目录指纹与隔离窗{win['window_code']}拧了"
                    f"（目录已变更，窗记 {recorded}，现算 {live}），"
                    "已拦住清洗调度入库",
                    409,
                )
            if not provided:
                raise ServiceError(
                    f"隔离窗{win['window_code']}开窗中，清洗调度未携带目录指纹，"
                    "已拦住入库",
                    409,
                )
            if provided != recorded:
                raise ServiceError(
                    f"目录指纹与隔离窗{win['window_code']}凭证不符"
                    f"（携带 {provided}，窗记 {recorded}），已拦住清洗调度入库",
                    409,
                )
        seq = conn.execute(
            "SELECT COUNT(*) AS c FROM ingest_batches"
        ).fetchone()["c"] + 1
        batch_code = f"CLN-{seq:04d}"
        cur = conn.execute(
            "INSERT INTO ingest_batches(batch_code, node_id, node_code, "
            "catalog_fingerprint, status, message) VALUES (?,?,?,?,'已入库',?)",
            (
                batch_code,
                node_id,
                node["node_code"],
                provided,
                "指纹核齐，准予入库" if windows else "无隔离窗，直接入库",
            ),
        )
        return dict(
            conn.execute(
                "SELECT * FROM ingest_batches WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        )
