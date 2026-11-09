// Dialog ubah data (lokasi, kamera, pengguna, watchlist): isi form dari data-row lalu tampilkan.
function openEdit(btn) {
  const d = document.getElementById('dlg'), f = d.querySelector('form'), r = JSON.parse(btn.dataset.row);
  f.action = f.dataset.base + r.id + (f.dataset.suffix || '');
  for (const [k, v] of Object.entries(r)) {
    const el = f.elements[k]; if (!el) continue;
    if (el.type === 'checkbox') el.checked = !!+v; else el.value = (v ?? '');
  }
  d.querySelectorAll('details').forEach(x => x.open = [...x.querySelectorAll('input')].some(i => i.value !== ''));  // buka bagian opsional bila terisi
  d.showModal();
}
function testCam(id, btn) {
  const out = btn.nextElementSibling; out.textContent = 'menguji…'; out.className = 'text-xs text-gray-500';
  fetch('/api/v1/calibration/snapshot/' + id).then(async r => {
    if (!r.ok) { out.textContent = (await r.json()).detail || 'gagal'; out.className = 'text-xs text-red-300'; }
    else { const d = await r.json(); out.textContent = `OK ${d.w}×${d.h}`; out.className = 'text-xs text-emerald-400'; }
  }).catch(() => { out.textContent = 'gagal'; out.className = 'text-xs text-red-300'; });
}
