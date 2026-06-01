/* verify.js — VLinker FS verification mode */

(function () {
  'use strict';

  const portSelect = document.getElementById('vlinker-port-select');
  const portInfo = document.getElementById('vlinker-port-info');
  const btnRefreshPorts = document.getElementById('btn-refresh-ports');
  const cyclesInput = document.getElementById('cycles-input');
  const btnRun = document.getElementById('btn-run-verify');
  const btnStop = document.getElementById('btn-stop-verify');
  const statusText = document.getElementById('verify-status-text');

  const progressCard = document.getElementById('verify-progress-card');
  const connectInfo = document.getElementById('verify-connect-info');
  const progressBar = document.getElementById('verify-progress-bar');
  const progressLabel = document.getElementById('verify-progress-label');

  const snapshotCard = document.getElementById('snapshot-card');
  const snapshotTbody = document.getElementById('snapshot-tbody');

  const reportCard = document.getElementById('report-card');
  const reportTbody = document.getElementById('report-tbody');
  const verdictBanner = document.getElementById('verdict-banner');

  let portData = [];
  let eventSource = null;

  // ---- Port loading ----
  function loadPorts() {
    fetch('/api/ports')
      .then(r => r.json())
      .then(ports => {
        portData = ports;
        portSelect.innerHTML = '<option value="">— select VLinker FS port —</option>';
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

  btnRefreshPorts.addEventListener('click', loadPorts);

  // ---- Run verify ----
  btnRun.addEventListener('click', () => {
    const port = portSelect.value;
    if (!port) { setStatus('Select VLinker FS port first', 'error'); return; }

    const cycles = parseInt(cyclesInput.value, 10) || 20;

    // Reset UI
    snapshotCard.style.display = 'none';
    reportCard.style.display = 'none';
    snapshotTbody.innerHTML = '';
    reportTbody.innerHTML = '';
    progressBar.style.width = '0%';
    progressLabel.textContent = 'Starting...';
    progressCard.style.display = 'block';
    connectInfo.textContent = '';

    btnRun.style.display = 'none';
    btnStop.style.display = 'inline-block';
    setStatus('Starting verify session...', '');

    fetch('/api/verify/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port, cycles }),
    })
      .then(r => r.json())
      .then(d => {
        if (!d.ok) {
          setStatus('Error: ' + d.error, 'error');
          btnRun.style.display = 'inline-block';
          btnStop.style.display = 'none';
          return;
        }
        startStream();
      })
      .catch(e => {
        setStatus('Error: ' + e, 'error');
        btnRun.style.display = 'inline-block';
        btnStop.style.display = 'none';
      });
  });

  btnStop.addEventListener('click', () => {
    fetch('/api/verify/stop', { method: 'POST' });
    stopStream();
    setStatus('Stopped', '');
    btnRun.style.display = 'inline-block';
    btnStop.style.display = 'none';
  });

  // ---- SSE stream ----
  function startStream() {
    stopStream();
    eventSource = new EventSource('/api/verify/stream');
    eventSource.onmessage = e => {
      try {
        const event = JSON.parse(e.data);
        handleEvent(event);
      } catch (_) {}
    };
    eventSource.onerror = () => {
      setStatus('Stream disconnected', 'error');
      stopStream();
    };
  }

  function stopStream() {
    if (eventSource) { eventSource.close(); eventSource = null; }
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case 'status':
        setStatus(ev.message, '');
        connectInfo.textContent = ev.message;
        break;

      case 'connected':
        connectInfo.textContent = ev.message;
        setStatus('Connected to ECU', 'ok');
        break;

      case 'error':
        setStatus('Error: ' + ev.message, 'error');
        connectInfo.textContent = 'Error: ' + ev.message;
        btnRun.style.display = 'inline-block';
        btnStop.style.display = 'none';
        stopStream();
        break;

      case 'snapshot_done':
        renderSnapshot(ev.results);
        snapshotCard.style.display = 'block';
        break;

      case 'cycle':
        const pct = Math.round(ev.cycle / ev.total * 100);
        progressBar.style.width = pct + '%';
        progressLabel.textContent = `Cycle ${ev.cycle} / ${ev.total}  ·  ${ev.pass}/${ev.pid_count} passed this cycle`;
        setStatus(`Running — ${pct}%`, '');
        break;

      case 'done':
        renderReport(ev.report);
        reportCard.style.display = 'block';
        progressBar.style.width = '100%';
        progressLabel.textContent = 'Complete';
        setStatus('Verify complete', 'ok');
        btnRun.style.display = 'inline-block';
        btnStop.style.display = 'none';
        stopStream();
        break;
    }
  }

  // ---- Render snapshot ----
  function renderSnapshot(results) {
    snapshotTbody.innerHTML = '';
    results.forEach(r => {
      const tr = document.createElement('tr');
      const badge = statusBadge(r.status);
      tr.innerHTML = [
        `<td>${badge}</td>`,
        `<td><code>${esc(r.pid)}</code></td>`,
        `<td>${esc(r.name)}</td>`,
        `<td>${r.actual !== null && r.actual !== undefined ? r.actual.toFixed(3) : '—'}</td>`,
        `<td>${r.expected !== undefined ? r.expected : '—'}</td>`,
        `<td>${r.diff !== null && r.diff !== undefined ? r.diff.toFixed(4) : '—'}</td>`,
        `<td>${esc(r.unit)}</td>`,
      ].join('');
      snapshotTbody.appendChild(tr);
    });
  }

  // ---- Render report ----
  function renderReport(rows) {
    reportTbody.innerHTML = '';
    let totalAttempts = 0, totalCorrect = 0;

    rows.forEach(r => {
      totalAttempts += r.attempts;
      totalCorrect += r.correct;

      const rate = r.rate;
      const rateClass = rate >= 95 ? 'rate-green' : rate >= 70 ? 'rate-yellow' : 'rate-red';
      const fillPct = Math.round(rate);
      const badge = rate >= 95
        ? '<span class="badge badge-pass">&#10003;</span>'
        : rate >= 70
          ? '<span class="badge badge-noresp">&#9888;</span>'
          : '<span class="badge badge-fail">&#10007;</span>';

      const tr = document.createElement('tr');
      tr.innerHTML = [
        `<td>${badge}</td>`,
        `<td><code>${esc(r.pid)}</code></td>`,
        `<td>${esc(r.name)}</td>`,
        `<td>${r.attempts}</td>`,
        `<td>${r.correct}</td>`,
        `<td>${r.no_resp}</td>`,
        `<td>${r.wrong}</td>`,
        `<td>${rate.toFixed(1)}%</td>`,
        `<td><span class="rate-bar"><span class="rate-fill ${rateClass}" style="width:${fillPct}%"></span></span></td>`,
      ].join('');
      reportTbody.appendChild(tr);
    });

    // Verdict
    const overallRate = totalAttempts > 0 ? (totalCorrect / totalAttempts * 100) : 0;
    let cls, msg;
    if (overallRate >= 95) {
      cls = 'verdict-excellent';
      msg = `&#127881; EXCELLENT — ${overallRate.toFixed(1)}% reliability. Emulator is working perfectly!`;
    } else if (overallRate >= 80) {
      cls = 'verdict-good';
      msg = `&#9888; GOOD — ${overallRate.toFixed(1)}% reliability. Some PIDs need attention.`;
    } else if (overallRate >= 60) {
      cls = 'verdict-fair';
      msg = `&#9888; FAIR — ${overallRate.toFixed(1)}% reliability. Check wiring and termination.`;
    } else {
      cls = 'verdict-poor';
      msg = `&#10007; POOR — ${overallRate.toFixed(1)}% reliability. Check CAN bus connection.`;
    }

    verdictBanner.className = 'verdict-banner ' + cls;
    verdictBanner.innerHTML = msg;
  }

  function statusBadge(status) {
    if (status === 'PASS') return '<span class="badge badge-pass">PASS &#10003;</span>';
    if (status === 'FAIL') return '<span class="badge badge-fail">FAIL &#10007;</span>';
    return '<span class="badge badge-noresp">NO RESP</span>';
  }

  function setStatus(msg, cls) {
    statusText.textContent = msg;
    statusText.className = 'status-text ' + (cls || '');
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  loadPorts();
})();
