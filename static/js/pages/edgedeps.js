import { api } from '../api.js';

export async function renderEdgeDeps(view, setMsg) {
  const j = await api('/api/edges/deps');
  const rows = (j.items || []).map((e) => {
    const iso = [];
    if (e.upstream_isolated) iso.push('上游隔离');
    if (e.downstream_isolated) iso.push('下游隔离');
    const part = e.in_impact ? '参与影响' : '不参与影响';
    return `<tr>
      <td>${e.edge_code}</td>
      <td>${e.upstream_code} → ${e.downstream_code}</td>
      <td>${e.transform_kind}</td>
      <td><span class="tag">${e.status}</span></td>
      <td>${iso.length ? `<span class="tag">${iso.join(' · ')}</span>` : '<span class="muted">—</span>'}</td>
      <td>${e.in_impact ? part : `<span class="err">${part}</span>`}</td>
    </tr>`;
  }).join('');
  view.innerHTML = `
    <section class="card">
      <h2>边依赖附页</h2>
      <p class="muted">隔离口径：${j.isolation_scope} · 当前已隔离节点数：${j.isolated_total}。
        严格口径下，沾隔离节点的已发布边不参与影响展开。</p>
      <table style="width:100%;border-collapse:collapse;font-size:.9rem">
        <thead><tr style="text-align:left;color:var(--muted)">
          <th style="padding:.4rem">边号</th><th style="padding:.4rem">依赖</th>
          <th style="padding:.4rem">变换</th><th style="padding:.4rem">状态</th>
          <th style="padding:.4rem">隔离标记</th><th style="padding:.4rem">影响参与</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="6" class="muted" style="padding:.4rem">暂无边</td></tr>'}</tbody>
      </table>
    </section>`;
}
