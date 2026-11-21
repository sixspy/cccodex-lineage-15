import { api } from '../api.js';

export async function renderRevisions(view, setMsg) {
  const rev = await api('/api/revisions');
  const nodes = await api('/api/nodes');
  const batches = await api('/api/ingest');
  const nodeOpts = (nodes.items || [])
    .map((n) => `<option value="${n.id}">${n.node_code}（${n.layer}）</option>`).join('');
  view.innerHTML = `
    <section class="card">
      <h2>目录修订隔离窗</h2>
      <p class="muted">当前已隔离节点数：${rev.isolated_total} · 安置落点：独立账册（凭证记目录指纹供核齐）</p>
      <div class="row">
        <label>目录范围<select id="scope">
          <option value="ALL">全目录</option><option>ODS</option>
          <option>DWD</option><option>DWS</option><option>ADS</option>
        </select></label>
        <button class="primary" id="open" type="button">打开隔离窗</button>
      </div>
    </section>
    <section class="card" style="margin-top:1rem">
      <h2>清洗调度入库</h2>
      <div class="row">
        <label>入库节点<select id="inode">${nodeOpts}</select></label>
        <label>目录指纹<input id="ifp" placeholder="开窗中须携带窗记指纹" /></label>
        <button class="primary" id="ingest" type="button">调度入库</button>
      </div>
      <div class="wall" style="margin-top:.75rem">
        ${(batches.items || []).slice(0, 6).map((b) => `<article class="card">
          <h3>${b.batch_code} · ${b.node_code}</h3>
          <span class="tag">${b.status}</span>
          <p class="muted">指纹 ${b.catalog_fingerprint || '（未携带）'} · ${b.message}</p>
        </article>`).join('') || '<p class="muted">暂无入库批次</p>'}
      </div>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(rev.items || []).map((w) => `<article class="card">
        <h3>${w.window_code}</h3>
        <span class="tag">${w.status}</span>
        <span class="tag">隔离来源：${w.isolation_source}</span>
        <span class="tag">${w.scope === 'ALL' ? '全目录' : w.scope}</span>
        <p>目录指纹 <b>${w.catalog_fingerprint}</b></p>
        <p class="muted">窗内节点 ${w.node_count} · 账册凭证 ${w.voucher_count} · ${w.opened_by || '—'} 开于 ${w.opened_at}</p>
        ${w.closed_at ? `<p class="muted">关窗于 ${w.closed_at}</p>` : ''}
        <div class="row">
          ${w.status === '开窗中' ? `<button data-close="${w.id}" type="button">关窗</button>` : ''}
          <button data-v="${w.id}" type="button">凭证账册</button>
        </div>
        <pre class="muted" id="v${w.id}"></pre>
      </article>`).join('') || '<p class="muted">暂无修订隔离窗</p>'}
    </section>`;
  document.getElementById('open').onclick = async () => {
    try {
      const r = await api('/api/revisions/open', {
        method: 'POST',
        body: JSON.stringify({ scope: document.getElementById('scope').value }),
      });
      setMsg('隔离窗 ' + r.item.window_code + ' 已开，凭证 ' + r.item.node_count + ' 张一次写入');
      await renderRevisions(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
  document.getElementById('ingest').onclick = async () => {
    try {
      const r = await api('/api/ingest', {
        method: 'POST',
        body: JSON.stringify({
          node_id: Number(document.getElementById('inode').value),
          catalog_fingerprint: document.getElementById('ifp').value,
        }),
      });
      setMsg('批次 ' + r.item.batch_code + ' · ' + r.item.message);
      await renderRevisions(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
  view.querySelectorAll('[data-close]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api('/api/revisions/' + btn.dataset.close + '/close', { method: 'POST', body: '{}' });
        setMsg('隔离窗已关，节点解除隔离');
        await renderRevisions(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-v]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/revisions/' + btn.dataset.v + '/vouchers');
        document.getElementById('v' + btn.dataset.v).textContent = (r.items || [])
          .map((v) => v.voucher_code + ' · ' + v.node_code + ' · ' + v.source_mark + ' · 指纹 ' + v.catalog_fingerprint)
          .join('\n') || '无凭证';
      } catch (e) { setMsg(e.message, true); }
    };
  });
}
