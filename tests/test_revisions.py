import threading

import pytest

from app.services import impact, ingest, nodes, revisions, settings
from app.services.errors import ServiceError


def _node_id(db_path, code):
    return next(n for n in nodes.list_nodes(db_path=db_path) if n["node_code"] == code)["id"]


def test_open_window_writes_vouchers_once(db_path):
    win = revisions.open_window("DWS", "仓管甲", db_path=db_path)
    assert win["status"] == "开窗中"
    assert win["isolation_source"] == "独立账册"
    assert win["catalog_fingerprint"]
    vouchers = revisions.list_vouchers(int(win["id"]), db_path=db_path)
    assert len(vouchers) == win["node_count"] == 1
    assert vouchers[0]["node_code"] == "N-DWS-REV"
    # 凭证记下目录指纹供核齐，来源标记与窗一致
    assert vouchers[0]["catalog_fingerprint"] == win["catalog_fingerprint"]
    assert vouchers[0]["source_mark"] == "独立账册"


def test_open_same_scope_twice_blocked_no_double_vouchers(db_path):
    revisions.open_window("DWS", "仓管甲", db_path=db_path)
    with pytest.raises(ServiceError) as exc:
        revisions.open_window("DWS", "仓管乙", db_path=db_path)
    assert "已有开窗中的隔离窗" in exc.value.message
    wins = [w for w in revisions.list_windows(db_path=db_path) if w["status"] == "开窗中"]
    assert len(wins) == 1
    assert revisions.isolated_total(db_path=db_path) == 1


def test_concurrent_open_single_winner(db_path):
    results, errors = [], []

    def race(who):
        try:
            results.append(revisions.open_window("ALL", who, db_path=db_path))
        except ServiceError as exc:
            errors.append(exc.message)

    threads = [threading.Thread(target=race, args=(f"仓管{i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 1
    assert len(errors) == 1 and "已有开窗中的隔离窗" in errors[0]
    win = results[0]
    vouchers = revisions.list_vouchers(int(win["id"]), db_path=db_path)
    # 串行闸生效：凭证不双写，一窗一节点一凭证
    assert len(vouchers) == win["node_count"] == 7
    assert len({v["node_id"] for v in vouchers}) == 7


def test_impact_strict_cuts_isolated_edges(db_path):
    revisions.open_window("DWS", "仓管甲", db_path=db_path)
    job = impact.start_impact(_node_id(db_path, "N-DWD-ORD"), db_path=db_path)
    assert job["affected_count"] == 1  # 只剩根节点，DWS 边被截断
    assert job["isolated_count"] == 1
    assert "隔离跳过 1" in job["message"]
    overview = impact.impact_overview(db_path=db_path)
    assert overview["isolated_total"] == 1
    assert overview["isolation_scope"] == "严格"
    detail = impact.job_detail(int(job["id"]), db_path=db_path)
    assert {h["node_code"] for h in detail["hits"]} == {"N-DWD-ORD"}


def test_impact_lenient_passes_through_but_hides(db_path):
    revisions.open_window("DWS", "仓管甲", db_path=db_path)
    settings.update_setting("isolation_scope", "宽松", db_path=db_path)
    job = impact.start_impact(_node_id(db_path, "N-DWD-ORD"), db_path=db_path)
    assert job["affected_count"] == 3  # DWS 不穿命中但边可穿
    assert job["isolated_count"] == 1
    detail = impact.job_detail(int(job["id"]), db_path=db_path)
    assert {h["node_code"] for h in detail["hits"]} == {
        "N-DWD-ORD",
        "N-ADS-DASH",
        "N-ADS-ALERT",
    }


def test_impact_root_isolated_blocked(db_path):
    revisions.open_window("DWD", "仓管甲", db_path=db_path)
    with pytest.raises(ServiceError) as exc:
        impact.start_impact(_node_id(db_path, "N-DWD-ORD"), db_path=db_path)
    assert "修订隔离窗内" in exc.value.message


def test_ingest_blocked_when_fingerprint_mismatches_window(db_path):
    win = revisions.open_window("DWS", "仓管甲", db_path=db_path)
    dws_id = _node_id(db_path, "N-DWS-REV")
    # 指纹对齐：准予入库
    ok = ingest.ingest_batch(dws_id, win["catalog_fingerprint"], db_path=db_path)
    assert ok["status"] == "已入库"
    # 携带错误指纹：拦住
    with pytest.raises(ServiceError) as exc:
        ingest.ingest_batch(dws_id, "deadbeef", db_path=db_path)
    assert "已拦住清洗调度入库" in exc.value.message
    # 目录变更后与窗记指纹拧了：拦住
    nodes.register_node("N-DWS-NEW", "dws_new", "DWS", "分析组", db_path=db_path)
    with pytest.raises(ServiceError) as exc2:
        ingest.ingest_batch(dws_id, win["catalog_fingerprint"], db_path=db_path)
    assert "拧了" in exc2.value.message


def test_ingest_outside_window_scope_passes(db_path):
    revisions.open_window("DWS", "仓管甲", db_path=db_path)
    ok = ingest.ingest_batch(_node_id(db_path, "N-ODS-ORD"), db_path=db_path)
    assert ok["status"] == "已入库"


def test_close_window_releases_isolation(db_path):
    win = revisions.open_window("DWS", "仓管甲", db_path=db_path)
    closed = revisions.close_window(int(win["id"]), db_path=db_path)
    assert closed["status"] == "已关窗"
    assert revisions.isolated_total(db_path=db_path) == 0
    job = impact.start_impact(_node_id(db_path, "N-DWD-ORD"), db_path=db_path)
    assert job["affected_count"] == 4
    with pytest.raises(ServiceError) as exc:
        revisions.close_window(int(win["id"]), db_path=db_path)
    assert "已关闭" in exc.value.message


def test_isolation_scope_setting_guard(db_path):
    keys = {s["key"]: s for s in settings.list_settings(db_path=db_path)}
    assert keys["isolation_scope"]["label"] == "隔离口径"
    with pytest.raises(ServiceError) as exc:
        settings.update_setting("isolation_scope", "随便", db_path=db_path)
    assert "隔离口径只许" in exc.value.message


def test_edge_deps_marks_isolated(db_path):
    from app.services import edges

    revisions.open_window("DWS", "仓管甲", db_path=db_path)
    deps = edges.list_edge_deps(db_path=db_path)
    assert deps["isolated_total"] == 1
    e03 = next(e for e in deps["items"] if e["edge_code"] == "E-03")
    assert e03["downstream_isolated"] and not e03["in_impact"]
    e01 = next(e for e in deps["items"] if e["edge_code"] == "E-01")
    assert not e01["downstream_isolated"] and e01["in_impact"]
