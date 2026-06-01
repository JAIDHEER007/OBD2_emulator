/* dashboard.js — Live log viewer and Arduino port management */

(function () {
  'use strict';

  let eventSource = null;
  let paused = false;
  let entries = [];
  let statsRx = 0, statsTx = 0, statsErr = 0;

  const tbody = document.getElementById('log-tbody');
  const noMsg = document.getElementById('no-log-msg');
  const wrapper = document.getElementById('log-table-wrapper');
  const countBadge = document.getElementById('log-count');
  const statRx = document.getElementById('stat-rx');
  const statTx = document.getElementById('stat-tx');
  const statErr = document.getElementById('stat-err');
  const connectStatus = document.getElementById('connect-status');
  const portSelect = document.getElementById('port-select');
  const portInfo = document.getElementById('port-info');
  const btnConnect = document.getElementById('btn-connect');
  const btnDisconnect = document.getElementById('btn-disconnect');
  const btnPush = document.getElementById('btn-push');
  const btnPause = document.getElementById('btn-pause');
  const btnClear = document.getElementById('btn-clear');
  const btnSave = document.getElementById('btn-save');

  let portData = [];

  // ---- Port loading ----
  function loadPorts() {
    fetch('/api/ports')
      .then(r => r.json())
      .then(ports => {
        portData = ports;
        portSelect.innerHTML = '<option value="">— select port —</option>';
        ports.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.device;
          opt.textContent = `${p.device}  ${p.manufacturer ? '│ ' + p.manufacturer : ''}`;
          portSelect.appendChild(opt);
        });
      });
  }

  portSelect.addEventListener('change', () => {
    const dev = portSelect.value;
    const info = portData.find(p => p.device === dev);
    if (info) {
      portInfo.style.display = 'block';
      portInfo.textContent = [
        info.device,
        info.manufacturer && `Mfr: ${info.manufacturer}`,
        info.description && `Desc: ${info.description}`,
        info.udev,
      ].filter(Boolean).join('  |  ');
    } else {
      portInfo.style.display = 'none';
    }
  });

  // ---- Connect / Disconnect ----
  btnConnect.addEventListener('click', () => {
    const port = portSelect.value;
    if (!port) { setStatus('Select a port first', 'error'); return; }

    setStatus('Connecting...', '');
    fetch('/api/arduino/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.ok) {
          setStatus(`Connected to ${port}`, 'ok');
          startSSE();
        } else {
          setStatus('Error: ' + d.error, 'error');
        }
      })
      .catch(e => setStatus('Error: ' + e, 'error'));
  });

  btnDisconnect.addEventListener('click', () => {
    fetch('/api/arduino/disconnect', { method: 'POST' })
      .then(() => {
        setStatus('Disconnected', '');
        stopSSE();
      });
  });

  btnPush.addEventListener('click', () => {
    fetch('/api/arduino/push', { method: 'POST' })
      .then(r => r.json())
      .then(d => setStatus(d.ok ? 'Values pushed' : 'Not connected', d.ok ? 'ok' : 'error'));
  });

  // ---- Log controls ----
  btnPause.addEventListener('click', () => {
    paused = !paused;
    btnPause.textContent = paused ? '▶ Resume' : '⏸ Pause';
  });

  btnClear.addEventListener('click', () => {
    fetch('/api/log/clear', { method: 'POST' });
    entries = [];
    statsRx = statsTx = statsErr = 0;
    tbody.innerHTML = '';
    updateStats();
    noMsg.style.display = 'block';
    wrapper.style.display = 'none';
  });

  btnSave.addEventListener('click', () => {
    fetch('/api/log/save', { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        if (d.ok) setStatus(`Saved ${d.count} entries → ${d.filename}`, 'ok');
        else setStatus('Save failed', 'error');
      });
  });

  // ---- SSE ----
  function startSSE() {
    stopSSE();
    eventSource = new EventSource('/api/log/stream');
    eventSource.onmessage = e => {
      if (paused) return;
      try {
        const entry = JSON.parse(e.data);
        appendRow(entry);
      } catch (_) {}
    };
    eventSource.onerror = () => {
      setStatus('Stream disconnected', 'error');
    };
  }

  function stopSSE() {
    if (eventSource) { eventSource.close(); eventSource = null; }
  }

  function appendRow(entry) {
    const dir = entry.direction;
    if (dir === 'RX') statsRx++;
    else if (dir === 'TX') statsTx++;
    else if (dir === 'ERR') statsErr++;

    entries.push(entry);
    if (entries.length > 2000) entries.shift();

    const tr = document.createElement('tr');
    tr.innerHTML = [
      `<td>${entry.ts ? entry.ts.slice(11, 23) : ''}</td>`,
      `<td>${dirBadge(dir)}</td>`,
      `<td>${entry.can_id || ''}</td>`,
      `<td>${entry.mode || ''}</td>`,
      `<td>${entry.pid || ''}</td>`,
      `<td>${(entry.data || []).join(' ')}</td>`,
      `<td class="raw-cell">${esc(entry.raw || '')}</td>`,
    ].join('');

    if (tbody.children.length >= 1000) tbody.deleteRow(0);
    tbody.appendChild(tr);

    noMsg.style.display = 'none';
    wrapper.style.display = 'block';
    wrapper.scrollTop = wrapper.scrollHeight;
    updateStats();
  }

  function dirBadge(dir) {
    if (dir === 'RX') return '<span class="badge badge-rx">RX</span>';
    if (dir === 'TX') return '<span class="badge badge-tx">TX</span>';
    if (dir === 'ERR') return '<span class="badge badge-err">ERR</span>';
    return '';
  }

  function updateStats() {
    statRx.textContent = statsRx;
    statTx.textContent = statsTx;
    statErr.textContent = statsErr;
    countBadge.textContent = `${entries.length} entries`;
  }

  function setStatus(msg, cls) {
    connectStatus.textContent = msg;
    connectStatus.className = 'status-text ' + (cls || '');
  }

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Init
  loadPorts();

  // If already connected (page reload), start SSE immediately
  fetch('/api/arduino/status')
    .then(r => r.json())
    .then(d => {
      if (d.connected) {
        if (d.port) {
          portSelect.value = d.port;
          portSelect.dispatchEvent(new Event('change'));
        }
        setStatus(`Connected to ${d.port}`, 'ok');
        startSSE();
      }
    });
})();
