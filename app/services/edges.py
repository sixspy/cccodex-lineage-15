"""血缘边：创建、发布、作废；边依赖附页。"""
from __future__ import annotations

from app.db import get_db
from app.services import revisions as revisions_svc
from app.services.errors import ServiceError


def list_edges(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT e.*, u.node_code AS upstream_code, u.table_name AS upstream_table, "
            "d.node_code AS downstream_code, d.table_name AS downstream_table "
            "FROM lineage_edges e "
            "JOIN lineage_nodes u ON u.id=e.upstream_id "
            "JOIN lineage_nodes d ON d.id=e.downstream_id "
            "ORDER BY e.id"
        ).fetchall()
        return [dict(r) for r in rows]


def list_edge_deps(db_path: str | None = None) -> dict:
    """边依赖附页：每条边的上下游隔离标记与当前口径下是否参与影响。"""
    with get_db(db_path) as conn:
        isolated = revisions_svc.isolated_node_ids(conn)
        scope = revisions_svc.isolation_scope(conn)
        rows = conn.execute(
            "SELECT e.*, u.node_code AS upstream_code, u.table_name AS upstream_table, "
            "d.node_code AS downstream_code, d.table_name AS downstream_table "
            "FROM lineage_edges e "
            "JOIN lineage_nodes u ON u.id=e.upstream_id "
            "JOIN lineage_nodes d ON d.id=e.downstream_id "
            "ORDER BY e.id"
        ).fetchall()
        items = []
        for r in rows:
            it = dict(r)
            it["upstream_isolated"] = int(it["upstream_id"]) in isolated
            it["downstream_isolated"] = int(it["downstream_id"]) in isolated
            touches = it["upstream_isolated"] or it["downstream_isolated"]
            # 严格口径下，沾隔离节点的已发布边不再参与影响展开。
            it["in_impact"] = it["status"] == "已发布" and not (
                touches and scope == "严格"
            )
            items.append(it)
        return {
            "items": items,
            "isolation_scope": scope,
            "isolated_total": len(isolated),
        }


def create_edge(
    edge_code: str,
    upstream_id: int,
    downstream_id: int,
    transform_kind: str = "直抽",
    note: str = "",
    db_path: str | None = None,
) -> dict:
    edge_code = (edge_code or "").strip()
    if not edge_code:
        raise ServiceError("边编号必填")
    if upstream_id == downstream_id:
        raise ServiceError("上下游不能是同一节点")
    with get_db(db_path) as conn:
        up = conn.execute(
            "SELECT * FROM lineage_nodes WHERE id=?", (upstream_id,)
        ).fetchone()
        down = conn.execute(
            "SELECT * FROM lineage_nodes WHERE id=?", (downstream_id,)
        ).fetchone()
        if not up or not down:
            raise ServiceError("上下游节点不存在", 404)
        if up["status"] == "停用" or down["status"] == "停用":
            raise ServiceError("停用节点不可建边", 409)
        try:
            cur = conn.execute(
                "INSERT INTO lineage_edges(edge_code, upstream_id, downstream_id, "
                "transform_kind, status, note) VALUES (?,?,?,?,'草稿',?)",
                (
                    edge_code,
                    upstream_id,
                    downstream_id,
                    transform_kind or "直抽",
                    note or "",
                ),
            )
        except Exception as exc:
            raise ServiceError(f"建边失败：{exc}") from exc
        return dict(
            conn.execute(
                "SELECT * FROM lineage_edges WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        )


def publish_edge(edge_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        edge = conn.execute(
            "SELECT * FROM lineage_edges WHERE id=?", (edge_id,)
        ).fetchone()
        if not edge:
            raise ServiceError("边不存在", 404)
        if edge["status"] != "草稿":
            raise ServiceError("仅草稿可发布", 409)
        for nid in (edge["upstream_id"], edge["downstream_id"]):
            node = conn.execute(
                "SELECT status FROM lineage_nodes WHERE id=?", (nid,)
            ).fetchone()
            if not node or node["status"] == "停用":
                raise ServiceError("上下游须有效", 409)
            if node["status"] == "登记":
                conn.execute(
                    "UPDATE lineage_nodes SET status='在用' WHERE id=?", (nid,)
                )
        conn.execute(
            "UPDATE lineage_edges SET status='已发布' WHERE id=?", (edge_id,)
        )
        return dict(
            conn.execute(
                "SELECT * FROM lineage_edges WHERE id=?", (edge_id,)
            ).fetchone()
        )


def void_edge(edge_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        edge = conn.execute(
            "SELECT * FROM lineage_edges WHERE id=?", (edge_id,)
        ).fetchone()
        if not edge:
            raise ServiceError("边不存在", 404)
        if edge["status"] == "已作废":
            raise ServiceError("边已作废", 409)
        conn.execute(
            "UPDATE lineage_edges SET status='已作废' WHERE id=?", (edge_id,)
        )
        return dict(
            conn.execute(
                "SELECT * FROM lineage_edges WHERE id=?", (edge_id,)
            ).fetchone()
        )
