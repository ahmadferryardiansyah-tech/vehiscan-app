const $ = i => document.getElementById(i);
Chart.defaults.font.family = '"Barlow", system-ui, sans-serif'; Chart.defaults.color = '#47515B';
const COL = {SM: '#2A5B88', MP: '#3E8E8A', KS: '#D99A00', LT: '#B5502F', LB: '#7A4B8C'};
const GRID = '#E3E7E9';
let fc, mc;
function render(d) {
  $('m-total').textContent = d.total; $('m-speed').textContent = d.avg_speed;
  $('m-vio').textContent = d.violations; $('m-wl').textContent = d.watchlist_hits;
  if (!fc) fc = new Chart($('flow'), {data: {labels: [], datasets: [
    {type: 'bar', label: 'Volume', data: [], backgroundColor: '#2A5B88', yAxisID: 'y'},
    {type: 'line', label: 'Kecepatan (km/jam)', data: [], borderColor: '#1B2026', backgroundColor: '#1B2026', borderWidth: 2, pointRadius: 2, tension: 0, yAxisID: 'y1'}]},
    options: {scales: {y: {grid: {color: GRID}}, y1: {position: 'right', grid: {display: false}}, x: {grid: {display: false}}}, plugins: {legend: {labels: {boxWidth: 12}}}}});
  fc.data.labels = d.flow.map(x => x.h); fc.data.datasets[0].data = d.flow.map(x => x.n); fc.data.datasets[1].data = d.flow.map(x => x.s); fc.update();
  if (!mc) mc = new Chart($('mix'), {type: 'doughnut', data: {labels: [], datasets: [{data: [], backgroundColor: [], borderColor: '#FFFFFF', borderWidth: 2}]}, options: {plugins: {legend: {position: 'bottom', labels: {boxWidth: 12}}}}});
  mc.data.labels = d.mix.map(x => PK[x.pkji] || x.pkji); mc.data.datasets[0].data = d.mix.map(x => x.n); mc.data.datasets[0].backgroundColor = d.mix.map(x => COL[x.pkji] || '#74808A'); mc.update();
  $('ev').innerHTML = d.events.map(e => `<tr><td>${e.ts}</td><td>${e.camera}</td><td class="font-mono">${e.plate}</td><td>${e.pkji}</td><td>${e.speed}</td><td><span class="px-2 py-0.5 rounded text-xs ${e.status == 'watchlist' ? 'bg-red-500/20 text-red-300' : 'bg-amber-500/20 text-amber-300'}">${e.status}</span></td></tr>`).join('');
}
const poll = () => fetch('/api/v1/overview').then(r => r.json()).then(render).catch(() => {});
poll(); setInterval(poll, 5000);  // cukup polling 5 detik; tidak perlu WebSocket
