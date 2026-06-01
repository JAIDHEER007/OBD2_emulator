/* log_viewer.js — Saved log file browser with DataTables */

(function () {
  'use strict';

  const fileList = document.getElementById('file-list');
  const noFilesMsg = document.getElementById('no-files-msg');
  const fileListLoading = document.getElementById('file-list-loading');
  const detailTitle = document.getElementById('detail-title');
  const detailEmpty = document.getElementById('detail-empty');
  const detailContent = document.getElementById('detail-content');
  const detailMeta = document.getElementById('detail-meta');
  const detailTbody = document.getElementById('detail-tbody');
  const detailToolbar = document.getElementById('detail-toolbar');
  const btnRefresh = document.getElementById('btn-refresh-files');
  const btnExportJson = document.getElementById('btn-export-json');
  const btnExportCsv = document.getElementById('btn-export-csv');
  const btnDelete = document.getElementById('btn-delete-file');

  let dtInstance = null;
  let currentFile = null;
  let currentData = null;

  // ---- File list ----
  function loadFileList() {
    fileListLoading.style.display = 'block';
    fileList.style.display = 'none';
    noFilesMsg.style.display = 'none';

    fetch('/api/log/files')
      .then(r => r.json())
      .then(files => {
        fileListLoading.style.display = 'none';
        fileList.innerHTML = '';

        if (files.length === 0) {
          noFilesMsg.style.display = 'block';
          return;
        }

        fileList.style.display = 'block';
        files.forEach(f => {
          const li = document.createElement('li');
          li.className = 'file-list-item' + (f.name === currentFile ? ' selected' : '');
          li.dataset.name = f.name;
          const size = (f.size / 1024).toFixed(1);
          const ts = f.modified ? f.modified.slice(0, 19).replace('T', ' ') : '';
          li.innerHTML = `
            <div class="file-name">${esc(f.name)}</div>
            <div class="file-meta">${f.count} entries &nbsp;·&nbsp; ${size} KB &nbsp;·&nbsp; ${ts}</div>
          `;
          li.addEventListener('click', () => loadFile(f.name));
          fileList.appendChild(li);
        });
      })
      .catch(() => {
        fileListLoading.textContent = 'Failed to load files';
      });
  }

  // ---- File detail ----
  function loadFile(name) {
    currentFile = name;
    // Highlight selected
    fileList.querySelectorAll('.file-list-item').forEach(li => {
      li.classList.toggle('selected', li.dataset.name === name);
    });

    detailTitle.textContent = name;
    detailEmpty.style.display = 'none';
    detailContent.style.display = 'none';
    detailToolbar.style.display = 'none';

    fetch(`/api/log/files/${encodeURIComponent(name)}`)
      .then(r => r.json())
      .then(data => {
        currentData = data;
        renderDetail(data);
      })
      .catch(() => {
        detailTitle.textContent = 'Error loading ' + name;
        detailEmpty.style.display = 'block';
        detailEmpty.textContent = 'Failed to load file.';
      });
  }

  function renderDetail(data) {
    const entries = data.entries || [];
    detailMeta.textContent = `Saved: ${data.saved_at || ''}   |   ${entries.length} entries`;

    // Destroy existing DataTable instance
    if (dtInstance) { dtInstance.destroy(); dtInstance = null; }
    detailTbody.innerHTML = '';

    entries.forEach(e => {
      const tr = document.createElement('tr');
      tr.innerHTML = [
        `<td>${e.ts || ''}</td>`,
        `<td>${dirBadge(e.direction)}</td>`,
        `<td>${esc(e.can_id || '')}</td>`,
        `<td>${esc(e.mode || '')}</td>`,
        `<td>${esc(e.pid || '')}</td>`,
        `<td>${esc((e.data || []).join(' '))}</td>`,
        `<td>${esc(e.raw || '')}</td>`,
      ].join('');
      detailTbody.appendChild(tr);
    });

    detailContent.style.display = 'block';
    detailToolbar.style.display = 'flex';

    // Init DataTable
    if (typeof $ !== 'undefined' && $.fn.DataTable) {
      dtInstance = $('#detail-table').DataTable({
        pageLength: 25,
        order: [],
        language: { search: 'Filter:' },
        columnDefs: [{ targets: 6, orderable: false }],
      });
    }
  }

  // ---- Export ----
  btnExportJson.addEventListener('click', () => {
    if (!currentData || !currentFile) return;
    const blob = new Blob([JSON.stringify(currentData, null, 2)], { type: 'application/json' });
    downloadBlob(blob, currentFile);
  });

  btnExportCsv.addEventListener('click', () => {
    if (!currentData || !currentFile) return;
    const entries = currentData.entries || [];
    const header = 'ts,direction,can_id,mode,pid,data,raw\n';
    const rows = entries.map(e =>
      [e.ts, e.direction, e.can_id, e.mode, e.pid,
       (e.data || []).join(' '), e.raw]
        .map(v => JSON.stringify(v || '')).join(',')
    ).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    downloadBlob(blob, currentFile.replace('.json', '.csv'));
  });

  // ---- Delete ----
  btnDelete.addEventListener('click', () => {
    if (!currentFile) return;
    if (!confirm(`Delete ${currentFile}?`)) return;
    fetch(`/api/log/files/${encodeURIComponent(currentFile)}`, { method: 'DELETE' })
      .then(r => r.json())
      .then(d => {
        if (d.ok) {
          currentFile = null;
          currentData = null;
          detailTitle.textContent = 'Select a file';
          detailEmpty.textContent = 'No file selected.';
          detailEmpty.style.display = 'block';
          detailContent.style.display = 'none';
          detailToolbar.style.display = 'none';
          loadFileList();
        }
      });
  });

  btnRefresh.addEventListener('click', loadFileList);

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function dirBadge(dir) {
    if (dir === 'RX') return '<span class="badge badge-rx">RX</span>';
    if (dir === 'TX') return '<span class="badge badge-tx">TX</span>';
    if (dir === 'ERR') return '<span class="badge badge-err">ERR</span>';
    return '';
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  loadFileList();
})();
