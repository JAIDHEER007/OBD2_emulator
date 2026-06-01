/* pid_editor.js — PID value editor with validation and save */

(function () {
  'use strict';

  const table = document.getElementById('pid-table');
  const tbody = document.getElementById('pid-tbody');
  const loading = document.getElementById('pid-loading');
  const vinInput = document.getElementById('vin-input');
  const btnSave = document.getElementById('btn-save');
  const btnReset = document.getElementById('btn-reset');
  const saveStatus = document.getElementById('save-status');

  let schema = [];

  // ---- Load PIDs from API ----
  function loadPids() {
    loading.style.display = 'block';
    table.style.display = 'none';
    fetch('/api/pids')
      .then(r => r.json())
      .then(data => {
        schema = data.pids;
        vinInput.value = data.vin || '';
        renderTable(schema);
        loading.style.display = 'none';
        table.style.display = 'table';
      })
      .catch(e => {
        loading.textContent = 'Failed to load PIDs: ' + e;
      });
  }

  function renderTable(pids) {
    tbody.innerHTML = '';
    pids.forEach((p, idx) => {
      const tr = document.createElement('tr');
      tr.dataset.idx = idx;
      tr.innerHTML = `
        <td><input type="checkbox" class="pid-enabled" ${p.enabled ? 'checked' : ''}></td>
        <td><code>${p.pid}</code></td>
        <td>${esc(p.name)}</td>
        <td>
          <input type="number"
            class="pid-value"
            value="${p.human_value}"
            min="${p.min}"
            max="${p.max}"
            step="${step(p)}"
            data-min="${p.min}"
            data-max="${p.max}">
        </td>
        <td>${esc(p.unit)}</td>
        <td>${p.min}</td>
        <td>${p.max}</td>
        <td>${esc(p.description || '')}</td>
      `;
      tbody.appendChild(tr);

      // Live validation
      const input = tr.querySelector('.pid-value');
      input.addEventListener('input', () => validateInput(input));
    });
  }

  function step(p) {
    if (p.unit === 'RPM') return 1;
    if (p.unit === '%' || p.unit === '°C' || p.unit === '°') return 0.1;
    if (p.unit === 'V') return 0.01;
    if (p.unit === 'g/s') return 0.01;
    return 0.1;
  }

  function validateInput(input) {
    const min = parseFloat(input.dataset.min);
    const max = parseFloat(input.dataset.max);
    const val = parseFloat(input.value);
    if (isNaN(val) || val < min || val > max) {
      input.classList.add('error');
      input.classList.remove('ok');
      return false;
    }
    input.classList.remove('error');
    input.classList.add('ok');
    return true;
  }

  // ---- Save ----
  btnSave.addEventListener('click', () => {
    // Validate all inputs
    const inputs = tbody.querySelectorAll('.pid-value');
    let allOk = true;
    inputs.forEach(inp => { if (!validateInput(inp)) allOk = false; });
    if (!allOk) {
      setStatus('Fix validation errors before saving', 'error');
      return;
    }

    const rows = tbody.querySelectorAll('tr');
    const pids = [];
    rows.forEach((tr, idx) => {
      const p = schema[idx];
      pids.push({
        pid: p.pid,
        enabled: tr.querySelector('.pid-enabled').checked,
        human_value: parseFloat(tr.querySelector('.pid-value').value),
      });
    });

    setStatus('Saving...', '');
    fetch('/api/pids', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pids, vin: vinInput.value }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.ok) setStatus('Saved & pushed to Arduino', 'ok');
        else setStatus('Save failed', 'error');
      })
      .catch(e => setStatus('Error: ' + e, 'error'));
  });

  // ---- Reset ----
  btnReset.addEventListener('click', () => {
    if (!confirm('Reset all values to defaults?')) return;
    const rows = tbody.querySelectorAll('tr');
    rows.forEach((tr, idx) => {
      const p = schema[idx];
      tr.querySelector('.pid-value').value = p.default !== undefined ? p.default : p.human_value;
      tr.querySelector('.pid-enabled').checked = true;
      const input = tr.querySelector('.pid-value');
      input.classList.remove('error', 'ok');
    });
    setStatus('Reset to defaults (not saved)', '');
  });

  function setStatus(msg, cls) {
    saveStatus.textContent = msg;
    saveStatus.className = 'status-text ' + (cls || '');
    if (cls === 'ok') {
      setTimeout(() => { saveStatus.textContent = ''; saveStatus.className = 'status-text'; }, 3000);
    }
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  loadPids();
})();
