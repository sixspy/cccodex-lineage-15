"""目录修订隔离窗：开窗、关窗、凭证账册。

工程落点唯一：独立账册写隔离凭证并记下目录指纹供核齐；
不建影子草稿表，两种安置不可并存。
"""
from __future__ import annotations

import hashlib
import sqlite3

from app.db import get_db
from app.services.errors import ServiceError

ISOLATION_SOURCE = "独立账册"
SCOPES = ("ALL", "ODS", "DWD", "DWS", "ADS")


def _scope_nodes(conn, scope: str) -> list[sqlite3.Row]:
    if scope == "ALL":
        return conn.execute(
            "SELECT * FROM lineage_nodes WHERE status != '停用' ORDER BY node_code"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM lineage_nodes WHERE status != '停用' AND layer=? "
        "ORDER BY node_code",
        (scope,),
    ).fetchall()


def fingerprint_of(rows) -> str:
    """目录指纹：按节点编号排序后取规范串的哈希，供核齐。"""
    canonical = "\n".join(
        f"{r['node_code']}|{r['table_name']}|{r['layer']}|{r['status']}" for r in rows
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def live_fingerprint(conn, scope: str) -> str:
    return fingerprint_of(_scope_nodes(conn, scope))


def open_window(scope: str, opened_by: str = "", db_path: str | None = None) -> dict:
    """开窗：一次事务写入窗与全部凭证；BEGIN IMMEDIATE 作串行闸。

    两名仓管抢开同一范围时，后到者拿到写锁后会看见已存在的开窗，
    收到中文冲突提示，不会双写凭证。
    """
    scope = (scope or "").strip().upper()
    if scope not in SCOPES:
        raise ServiceError("目录范围只许 ALL/ODS/DWD/DWS/ADS")
    with get_db(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            dup = conn.execute(
                "SELECT window_code FROM revision_windows "
                "WHERE scope=? AND status='开窗中'",
                (scope,),
            ).fetchone()
            if dup:
                raise ServiceError(
                    f"该目录范围已有开窗中的隔离窗（{dup['window_code']}），不可重复开窗",
                    409,
                )
            rows = _scope_nodes(conn, scope)
            if not rows:
                raise ServiceError("该目录范围无有效节点，无法开窗")
            fingerprint = fingerprint_of(rows)
            seq = conn.execute(
                "SELECT COUNT(*) AS c FROM revision_windows"
            ).fetchone()["c"] + 1
            window_code = f"ISO-{seq:04d}"
            cur = conn.execute(
                "INSERT INTO revision_windows(window_code, scope, status, "
                "isolation_source, catalog_fingerprint, node_count, opened_by) "
                "VALUES (?,?,'开窗中',?,?,?,?)",
                (
                    window_code,
                    scope,
                    ISOLATION_SOURCE,
                    fingerprint,
                    len(rows),
                    opened_by or "",
                ),
            )
            window_id = cur.lastrowid
            for r in rows:
                conn.execute(
                    "INSERT INTO isolation_vouchers(voucher_code, window_id, "
                    "node_id, node_code, catalog_fingerprint, source_mark) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        f"{window_code}-{r['node_code']}",
                        window_id,
                        r["id"],
                        r["node_code"],
                        fingerprint,
                        ISOLATION_SOURCE,
                    ),
                )
        except ServiceError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ServiceError(f"开窗写入冲突，请重试：{exc}", 409) from exc
        except sqlite3.OperationalError as exc:
            raise ServiceError(f"开窗写入未完成：{exc}", 409) from exc
        return dict(
            conn.execute(
                "SELECT * FROM revision_windows WHERE id=?", (window_id,)
            ).fetchone()
        )


def close_window(window_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM revision_windows WHERE id=?", (window_id,)
        ).fetchone()
        if not row:
            raise ServiceError("隔离窗不存在", 404)
        if row["status"] != "开窗中":
            raise ServiceError("隔离窗已关闭，不可重复关窗", 409)
        conn.execute(
            "UPDATE revision_windows SET status='已关窗', closed_at=datetime('now') "
            "WHERE id=?",
            (window_id,),
        )
        return dict(
            conn.execute(
                "SELECT * FROM revision_windows WHERE id=?", (window_id,)
            ).fetchone()
        )


def list_windows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT w.*, "
            "(SELECT COUNT(*) FROM isolation_vouchers v WHERE v.window_id=w.id) "
            "AS voucher_count "
            "FROM revision_windows w ORDER BY w.id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def list_vouchers(window_id: int, db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        win = conn.execute(
            "SELECT id FROM revision_windows WHERE id=?", (window_id,)
        ).fetchone()
        if not win:
            raise ServiceError("隔离窗不存在", 404)
        rows = conn.execute(
            "SELECT v.*, n.table_name, n.layer FROM isolation_vouchers v "
            "JOIN lineage_nodes n ON n.id=v.node_id "
            "WHERE v.window_id=? ORDER BY v.node_code",
            (window_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def isolated_node_ids(conn) -> set[int]:
    """开窗中的凭证节点集合：影响分析与边依赖都以此为准。"""
    rows = conn.execute(
        "SELECT DISTINCT v.node_id FROM isolation_vouchers v "
        "JOIN revision_windows w ON w.id=v.window_id "
        "WHERE w.status='开窗中'"
    ).fetchall()
    return {int(r["node_id"]) for r in rows}


def isolated_total(db_path: str | None = None) -> int:
    with get_db(db_path) as conn:
        return len(isolated_node_ids(conn))


def isolation_scope(conn) -> str:
    row = conn.execute(
        "SELECT value FROM lab_settings WHERE key='isolation_scope'"
    ).fetchone()
    return (row["value"] if row else "严格") or "严格"


def covering_open_windows(conn, layer: str) -> list[sqlite3.Row]:
    """覆盖某层级的开窗：全目录窗与同层窗都算。"""
    return conn.execute(
        "SELECT * FROM revision_windows "
        "WHERE status='开窗中' AND (scope='ALL' OR scope=?)",
        (layer,),
    ).fetchall()
