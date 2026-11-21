import { api } from '../api.js';

export async function renderSettings(view, setMsg) {
  const j = await api('/api/settings');
  view.innerHTML = `
    <section class="card">
      <h2>台参数</h2>
      <div class="wall">
        ${(j.items || []).map((s) => `<article class="card">
          <h3>${s.label}</h3>
          <p class="muted">${s.key}</p>
          <div class="row">
            <input data-k="${s.key}" value="${s.value}" />
            <button data-save="${s.key}" class="primary" type="button">保存</button>
          </div>
        </article>`).join('')}
      </div>
    </section>`;
  view.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        const input = view.querySelector('input[data-k="' + btn.dataset.save + '"]');
        await api('/api/settings', {
          method: 'POST',
          body: JSON.stringify({ key: btn.dataset.save, value: input.value }),
        });
        setMsg('参数已保存');
        await renderSettings(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
}
