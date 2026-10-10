/* ============================================================
   Doc Cleaner — app.js
   Front-end logic for the pywebview desktop shell.
   Bridge contract (Python side, macapp/app.py):
     JS -> Py : pywebview.api.{pick_files, get_dropped_paths, convert,
                 cancel_batch, get_prefs, set_output_mode, set_output_format,
                 set_epub_zh_hant, set_translate_zh_hant, set_x_credentials,
                 check_gemini_key, get_app_info, pick_output_folder,
                 reveal_in_finder, preview_markdown, open_github}
     Py -> JS : init(lang, isMacos), onProgress(i, total), onResult(result),
                 onComplete(), onNotice(kind, n)
   ============================================================ */

/* ---------- i18n ---------- */

var STRINGS = {
  zh: {
    title:            '文件清洗工具',
    githubTitle:      'GitHub',
    aboutTitle:       '關於',
    dropZoneText:     '將文件拖放至此',
    dropZoneHint:     '或使用下方按鈕加入 · 支援 PDF、Office、EPUB 等 16 種格式',
    pickFiles:        '選擇檔案',
    addUrl:           '新增網址',
    urlPlaceholder:   '貼上 X (Twitter) 文章連結 (https://x.com/...)',
    clearFiles:       '清除選擇',
    outputLabel:      '輸出位置：',
    outputSibling:    '同資料夾',
    outputDesktop:    '桌面',
    outputCustom:     '選擇資料夾…',
    changeFolder:     '變更…',
    formatLabel:      '輸出格式：',
    formatMd:         'Markdown (.md)',
    formatEpub:       'EPUB 電子書 (.epub)',
    formatBoth:       '兩種格式 (.md + .epub)',
    promptLabel:      '提示詞模式：',
    promptAuto:       '自動偵測',
    promptTechnical:  '技術文件',
    promptFinance:    '金融文件',
    promptDefault:    '通用',
    langOptionsLabel: '語言與翻譯：',
    translateZhHant:  '英文轉繁體（英文翻譯成中文）',
    epubZhHant:       '簡轉繁（中文字形轉換）',
    xCredTitle:       '憑證設定',
    xToggle:          '顯示／收起',
    xCredHint:        '轉換 X 文章需登入 Cookies；憑證僅存於本機。',
    xAuthTokenPh:     '貼上 auth_token',
    xCt0Ph:           '貼上 ct0',
    xSave:            '儲存 X 憑證',
    convertIdleHint:  '加入文件後即可轉換',
    cancel:           '取消',
    convert:          '轉換',
    convertN:         '轉換 {n} 個文件',
    preparing:        '準備中…',
    done:             '完成',
    cancelled:        '已取消',
    cancelling:       '取消中…',
    loadingFiles:     '讀取中…',
    itemsSelected:    '已選 {n} 個項目',
    capNotice:        '只載入前 {n} 個檔案',
    fallbackSibling:  '輸出資料夾不存在，已改存到原始檔案所在資料夾',
    urlEmpty:         '請先貼上網址！',
    xSaved:           'X (Twitter) 憑證已儲存！',
    revealInFinder:   '在 Finder 顯示',
    preview:          '預覽',
    apiKeyDetected:   '(已偵測到 Gemini API 金鑰)',
    apiKeyMissing:    '(未設定 Gemini API 金鑰，使用本地翻譯)',
    sumOk:            '{n} 成功',
    sumSkip:          '{n} 跳過',
    sumFail:          '{n} 失敗'
  },
  en: {
    title:            'Doc Cleaner',
    githubTitle:      'GitHub',
    aboutTitle:       'About',
    dropZoneText:     'Drop files here',
    dropZoneHint:     'or add with the button below · PDF, Office, EPUB and 16 formats',
    pickFiles:        'Choose Files',
    addUrl:           'Add URL',
    urlPlaceholder:   'Paste X (Twitter) article URL (https://x.com/...)',
    clearFiles:       'Clear',
    outputLabel:      'Output:',
    outputSibling:    'Same folder',
    outputDesktop:    'Desktop',
    outputCustom:     'Choose folder…',
    changeFolder:     'Change…',
    formatLabel:      'Format:',
    formatMd:         'Markdown (.md)',
    formatEpub:       'EPUB e-book (.epub)',
    formatBoth:       'Both (.md + .epub)',
    promptLabel:      'Prompt Mode:',
    promptAuto:       'Auto Detect',
    promptTechnical:  'Technical Doc',
    promptFinance:    'Financial Doc',
    promptDefault:    'General',
    langOptionsLabel: 'Language & Translation:',
    translateZhHant:  'English to Traditional Chinese',
    epubZhHant:       'Convert Simplified to Traditional Chinese',
    xCredTitle:       'Credentials',
    xToggle:          'Show / Hide',
    xCredHint:        'Converting X articles requires login cookies; stored locally only.',
    xAuthTokenPh:     'Paste auth_token',
    xCt0Ph:           'Paste ct0',
    xSave:            'Save X credentials',
    convertIdleHint:  'Add documents to start converting',
    cancel:           'Cancel',
    convert:          'Convert',
    convertN:         'Convert {n} document(s)',
    preparing:        'Preparing…',
    done:             'Done',
    cancelled:        'Cancelled',
    cancelling:       'Cancelling…',
    loadingFiles:     'Loading…',
    itemsSelected:    '{n} item(s) selected',
    capNotice:        'Loaded first {n} files',
    fallbackSibling:  'Output folder missing; saved beside source files instead',
    urlEmpty:         'Please paste a URL first!',
    xSaved:           'X (Twitter) credentials saved!',
    revealInFinder:   'Show in Finder',
    preview:          'Preview',
    apiKeyDetected:   '(Gemini API Key detected)',
    apiKeyMissing:    '(No Gemini API Key, using local translation)',
    sumOk:            '{n} succeeded',
    sumSkip:          '{n} skipped',
    sumFail:          '{n} failed'
  }
};

var _lang = 'zh';
var selectedPaths = [];
var customDir = null;          // remembered custom output folder
var _converting = false;
var _summary = { ok: 0, skipped: 0, error: 0 };

function $(id) { return document.getElementById(id); }
function t(key) { return (STRINGS[_lang] && STRINGS[_lang][key]) || STRINGS.en[key] || key; }
function fmt(key, n) { return t(key).replace('{n}', String(n)); }

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ---------- Inline SVG icons ---------- */

var ICONS = {
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16 9.5"/></svg>',
  skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2.5 20h19z"/><line x1="12" y1="10" x2="12" y2="14.5"/><circle cx="12" cy="17.2" r="0.6" fill="currentColor"/></svg>',
  error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>',
  link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a5 5 0 0 0 7.07 0l3.18-3.18a5 5 0 0 0-7.07-7.07L11.5 5.4"/><path d="M14 10a5 5 0 0 0-7.07 0l-3.18 3.18a5 5 0 0 0 7.07 7.07l1.68-1.65"/></svg>'
};

/* ---------- Language ---------- */

function setLang(code) {
  _lang = (STRINGS[code] ? code : 'en');
  document.querySelectorAll('[data-i18n]').forEach(function (el) {
    var val = t(el.getAttribute('data-i18n'));
    el.textContent = val;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
    var val = t(el.getAttribute('data-i18n-placeholder'));
    el.setAttribute('placeholder', val);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
    el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
  });
  document.querySelectorAll('[data-i18n-aria-label]').forEach(function (el) {
    el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria-label')));
  });

  var toggle = $('btn-lang');
  if (toggle) toggle.textContent = (_lang === 'zh' ? 'EN' : 'ZH');

  renderFiles();
  updateConvertButton();
  renderSummary();
  refreshIdleHint();
}

/* ---------- Init — called from Python after page load ---------- */

function init(langCode, isMacos) {
  setLang(langCode);
  if (isMacos) {
    $('btn-lang').style.display = '';
  }

  pywebview.api.get_app_info().then(function (info) {
    $('about-ver').textContent = info.version;
  });

  pywebview.api.get_prefs().then(function (prefs) {
    if (!prefs) return;
    customDir = prefs.custom_output_dir || null;

    var mode = prefs.output_mode || 'sibling';
    var radio = document.querySelector('input[name=mode][value=' + mode + ']');
    if (radio) radio.checked = true;
    showCustomDir();
    $('custom-dir-row').style.display = (mode === 'custom') ? '' : 'none';

    var fmtv = prefs.output_format || 'md';
    var fmtRadio = document.querySelector('input[name=format][value=' + fmtv + ']');
    if (fmtRadio) fmtRadio.checked = true;

    $('chk-epub-zh-hant').checked = prefs.epub_zh_hant || false;
    $('chk-translate-zh-hant').checked = prefs.translate_zh_hant || false;

    var pmode = prefs.prompt_mode || 'auto';
    var pRadio = document.querySelector('input[name=prompt_mode][value=' + pmode + ']');
    if (pRadio) pRadio.checked = true;

    if (prefs.x_auth_token) $('input-x-auth-token').value = prefs.x_auth_token;
    syncXPanelVisibility();
  });

  pywebview.api.check_gemini_key().then(function (hasKey) {
    var statusSpan = $('api-key-status');
    if (!statusSpan) return;
    statusSpan.textContent = hasKey ? t('apiKeyDetected') : t('apiKeyMissing');
    statusSpan.style.color = hasKey ? 'var(--ok)' : 'var(--warn)';
  });
}

/* ---------- Toasts (replace alert()) ---------- */

function showToast(message, kind) {
  var stack = $('toast-stack');
  if (!stack) return;
  var toast = document.createElement('div');
  toast.className = 'toast' + (kind ? ' toast-' + kind : '');
  toast.textContent = message;
  stack.appendChild(toast);
  requestAnimationFrame(function () { toast.classList.add('show'); });
  setTimeout(function () {
    toast.classList.remove('show');
    setTimeout(function () { toast.remove(); }, 250);
  }, 3200);
}

/* ---------- Notices pushed from Python ---------- */

function onNotice(kind, n) {
  if (kind === 'cap') {
    var el = $('notice');
    el.textContent = fmt('capNotice', n);
    el.style.display = '';
  } else if (kind === 'fallbackSibling') {
    showToast(t('fallbackSibling'), 'warn');
  }
}

/* ---------- Custom output folder ---------- */

function showCustomDir() {
  var el = $('custom-dir-path');
  if (el) el.textContent = customDir || '';
}

function chooseOutputFolder() {
  pywebview.api.pick_output_folder().then(function (dir) {
    if (dir) {
      customDir = dir;
      showCustomDir();
      $('custom-dir-row').style.display = '';
    } else if (!customDir) {
      // Cancelled with no prior folder → revert to sibling
      document.querySelector('input[name=mode][value=sibling]').checked = true;
      $('custom-dir-row').style.display = 'none';
      pywebview.api.set_output_mode('sibling');
    }
  });
}

/* ---------- File queue ---------- */

function isUrlItem(p) {
  return p.indexOf('http://') === 0 || p.indexOf('https://') === 0 ||
         p.indexOf('x.com/') !== -1 || p.indexOf('twitter.com/') !== -1;
}

function extOf(p) {
  var m = /\.([A-Za-z0-9]+)$/.exec(p);
  return m ? m[1].toUpperCase() : '?';
}

function baseName(p) {
  return p.replace(/\\/g, '/').split('/').pop();
}

function renderFiles() {
  var list = $('file-list');
  var count = $('file-count');
  list.innerHTML = '';

  selectedPaths.forEach(function (p, idx) {
    var li = document.createElement('li');
    li.title = p;

    var badge = document.createElement('span');
    badge.className = 'file-kind';
    badge.textContent = isUrlItem(p) ? 'URL' : extOf(p);

    var label = document.createElement('span');
    label.className = 'file-item-label';
    var base = document.createElement('span');
    base.className = 'file-base';
    if (isUrlItem(p)) {
      base.innerHTML = ICONS.link + ' ';
      base.insertAdjacentHTML('beforeend', escHtml(p));
    } else {
      base.textContent = baseName(p);
    }
    label.appendChild(base);

    var rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'file-remove';
    rm.setAttribute('aria-label', 'remove');
    rm.dataset.idx = String(idx);
    rm.innerHTML = ICONS.x;
    rm.addEventListener('click', function (e) {
      e.stopPropagation();
      var i = parseInt(this.dataset.idx, 10);
      if (!isNaN(i)) {
        selectedPaths.splice(i, 1);
        renderFiles();
        syncXPanelVisibility();
        updateConvertButton();
      }
    });

    li.appendChild(badge);
    li.appendChild(label);
    li.appendChild(rm);
    list.appendChild(li);
  });

  var n = selectedPaths.length;
  count.textContent = n > 0 ? fmt('itemsSelected', n) : '';

  $('btn-clear').style.display = n > 0 ? '' : 'none';
  syncXPanelVisibility();
  updateConvertButton();
}

function syncXPanelVisibility() {
  // Contextual X panel: visible only while the queue holds an X/Twitter URL.
  var hasX = selectedPaths.some(isUrlItem);
  $('x-config-section').hidden = !hasX;
  if (!hasX) {
    $('x-config-box').style.display = 'none';
  }
}

function updateConvertButton() {
  var btn = $('btn-convert');
  var n = selectedPaths.length;
  btn.disabled = (n === 0) || _converting;
  btn.textContent = (n > 0 && !_converting) ? fmt('convertN', n) : t('convert');
}

function refreshIdleHint() {
  if (!_converting) {
    $('progress-status').textContent = t('convertIdleHint');
  }
}

$('btn-pick').addEventListener('click', function () {
  pywebview.api.pick_files().then(function (paths) {
    if (paths && paths.length) {
      paths.forEach(function (p) {
        if (selectedPaths.indexOf(p) === -1) selectedPaths.push(p);
      });
      renderFiles();
    }
  });
});

function addUrlFromInput() {
  var input = $('input-url');
  var rawUrl = input.value.trim();
  if (!rawUrl) {
    showToast(t('urlEmpty'), 'warn');
    return;
  }
  var url = rawUrl;
  if (!/^https?:\/\//i.test(url)) {
    url = 'https://' + url;
  }
  if (selectedPaths.indexOf(url) === -1) {
    selectedPaths.push(url);
  }
  input.value = '';
  renderFiles();
}

$('btn-add-url').addEventListener('click', function (e) {
  e.preventDefault();
  addUrlFromInput();
});

$('input-url').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    addUrlFromInput();
  }
});

$('btn-clear').addEventListener('click', function () {
  selectedPaths = [];
  renderFiles();
  $('results').innerHTML = '';
  $('result-summary').style.display = 'none';
  refreshIdleHint();
});

/* ---------- Drag and drop ---------- */

window.addEventListener('dragover', function (e) { e.preventDefault(); }, false);
window.addEventListener('drop', function (e) { e.preventDefault(); }, false);

var dz = $('drop-zone');
dz.addEventListener('dragover', function (e) { e.preventDefault(); dz.classList.add('hover'); });
dz.addEventListener('dragleave', function () { dz.classList.remove('hover'); });
dz.addEventListener('drop', function (e) {
  e.preventDefault();
  dz.classList.remove('hover');
  $('file-count').textContent = t('loadingFiles');

  // Hand the native drop event to pywebview's DnD listener, then pull the
  // resolved paths (files expanded recursively, filtered to supported types).
  if (window.pywebview && window.pywebview._jsApiCallback && e && e.dataTransfer) {
    try {
      if (!window.pywebview._returnValuesCallbacks) {
        window.pywebview._returnValuesCallbacks = {};
      }
      if (!window.pywebview._returnValuesCallbacks.dummy) {
        window.pywebview._returnValuesCallbacks.dummy = {};
      }
      window.pywebview._returnValuesCallbacks.dummy['1'] = function () {};
      window.pywebview._jsApiCallback('dummy', { event: e }, '1');
    } catch (err) {}
  }

  setTimeout(function () {
    pywebview.api.get_dropped_paths().then(function (paths) {
      if (paths && paths.length) {
        onDropPaths(paths);
      } else {
        $('file-count').textContent = '';
        renderFiles();
      }
    });
  }, 50);
});

function onDropPaths(paths) {
  paths.forEach(function (p) {
    if (selectedPaths.indexOf(p) === -1) selectedPaths.push(p);
  });
  renderFiles();
}

// Clicking anywhere on the hero (except interactive children) opens the picker.
dz.addEventListener('click', function (e) {
  if (e.target.closest('button, input, ul, .url-row')) return;
  $('btn-pick').click();
});
dz.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' || e.key === ' ') {
    if (e.target !== dz) return;
    e.preventDefault();
    $('btn-pick').click();
  }
});

/* ---------- Settings: segmented controls + checkboxes ---------- */

document.querySelectorAll('input[name=mode]').forEach(function (r) {
  r.addEventListener('change', function () {
    var mode = this.value;
    $('custom-dir-row').style.display = (mode === 'custom') ? '' : 'none';
    if (mode === 'custom' && !customDir) {
      chooseOutputFolder();
    } else {
      pywebview.api.set_output_mode(mode);
    }
  });
});

document.querySelectorAll('input[name=format]').forEach(function (r) {
  r.addEventListener('change', function () {
    pywebview.api.set_output_format(this.value);
  });
});

document.querySelectorAll('input[name=prompt_mode]').forEach(function (r) {
  r.addEventListener('change', function () {
    pywebview.api.set_prompt_mode(this.value);
  });
});

$('chk-epub-zh-hant').addEventListener('change', function () {
  pywebview.api.set_epub_zh_hant(this.checked);
});

$('chk-translate-zh-hant').addEventListener('change', function () {
  pywebview.api.set_translate_zh_hant(this.checked);
});

$('btn-change-folder').addEventListener('click', function () {
  chooseOutputFolder();
});

/* ---------- X credentials (contextual panel) ---------- */

$('btn-toggle-x-config').addEventListener('click', function () {
  var box = $('x-config-box');
  box.style.display = (box.style.display === 'none') ? 'block' : 'none';
});

$('btn-save-x-config').addEventListener('click', function () {
  var auth = $('input-x-auth-token').value.trim();
  var ct = $('input-x-ct0').value.trim();
  pywebview.api.set_x_credentials(auth, ct).then(function () {
    showToast(t('xSaved'), 'success');
  });
});

/* ---------- Convert / cancel ---------- */

$('btn-convert').addEventListener('click', function () {
  if (_converting || selectedPaths.length === 0) return;
  var mode = document.querySelector('input[name=mode]:checked').value;
  var format = document.querySelector('input[name=format]:checked').value;

  _converting = true;
  _summary = { ok: 0, skipped: 0, error: 0 };
  document.body.classList.add('is-converting');

  $('results').innerHTML = '';
  $('result-summary').style.display = 'none';
  $('notice').style.display = 'none';

  $('convert-progress').style.display = '';
  $('convert-progress-fill').style.width = '0%';
  $('progress-status').textContent = t('preparing');

  $('btn-cancel').style.display = '';
  $('btn-cancel').disabled = false;
  updateConvertButton();
  $('btn-pick').disabled = true;

  pywebview.api.convert(selectedPaths, mode, (mode === 'custom') ? customDir : null, format);
});

$('btn-cancel').addEventListener('click', function () {
  this.disabled = true;
  $('progress-status').textContent = t('cancelling');
  pywebview.api.cancel_batch();
});

/* ---------- Progress callbacks (pushed from Python) ---------- */

function onProgress(current, total) {
  $('progress-status').textContent = (_lang === 'zh')
    ? ('第 ' + current + ' / ' + total + ' 個')
    : (current + ' / ' + total);
  var pct = total > 0 ? Math.round(((current - 1) / total) * 100) : 0;
  $('convert-progress-fill').style.width = pct + '%';
}

function renderSummary() {
  var wrap = $('result-summary');
  if (_summary.ok + _summary.skipped + _summary.error === 0) {
    wrap.style.display = 'none';
    wrap.innerHTML = '';
    return;
  }
  wrap.style.display = '';
  wrap.innerHTML =
    '<span class="chip chip-ok">' + ICONS.ok + escHtml(fmt('sumOk', _summary.ok)) + '</span>' +
    '<span class="chip chip-skip">' + ICONS.skip + escHtml(fmt('sumSkip', _summary.skipped)) + '</span>' +
    '<span class="chip chip-fail">' + ICONS.error + escHtml(fmt('sumFail', _summary.error)) + '</span>';
}

function onResult(result) {
  var ok = result.status === 'ok';
  var skipped = result.status === 'skipped';

  if (ok) _summary.ok += 1;
  else if (skipped) _summary.skipped += 1;
  else _summary.error += 1;
  renderSummary();

  var ul = $('results');
  var li = document.createElement('li');

  var iconWrap = document.createElement('span');
  iconWrap.className = 'result-icon ' + (ok ? 'icon-ok' : (skipped ? 'icon-skip' : 'icon-error'));
  iconWrap.innerHTML = ok ? ICONS.ok : (skipped ? ICONS.skip : ICONS.error);

  var info = document.createElement('div');
  info.className = 'file-info';
  var nameEl = document.createElement('div');
  nameEl.className = 'file-name';
  nameEl.textContent = result.file;
  info.appendChild(nameEl);
  if (result.error) {
    var errEl = document.createElement('div');
    errEl.className = 'file-err';
    errEl.textContent = result.error;
    info.appendChild(errEl);
  }

  li.appendChild(iconWrap);
  li.appendChild(info);

  if (ok && result.output) {
    var actions = document.createElement('div');
    actions.className = 'result-actions';

    var pv = document.createElement('button');
    pv.type = 'button';
    pv.className = 'btn-reveal';
    pv.textContent = t('preview');
    pv.dataset.path = result.output;
    pv.addEventListener('click', function () { openPreview(this.dataset.path); });
    actions.appendChild(pv);

    var rv = document.createElement('button');
    rv.type = 'button';
    rv.className = 'btn-reveal';
    rv.textContent = t('revealInFinder');
    rv.dataset.path = result.output;
    rv.addEventListener('click', function () {
      pywebview.api.reveal_in_finder(this.dataset.path);
    });
    actions.appendChild(rv);

    li.appendChild(actions);
  }

  ul.appendChild(li);
}

function onComplete() {
  _converting = false;
  document.body.classList.remove('is-converting');

  $('convert-progress-fill').style.width = '100%';
  $('progress-status').textContent = t('done');
  $('btn-cancel').style.display = 'none';
  $('btn-pick').disabled = false;
  updateConvertButton();

  setTimeout(function () {
    $('convert-progress').style.display = 'none';
    $('convert-progress-fill').style.width = '0%';
  }, 1200);
}

/* ---------- Markdown preview overlay ---------- */

function openPreview(path) {
  pywebview.api.preview_markdown(path).then(function (html) {
    // Trust boundary: `html` is the Python renderer's escaped, whitelisted
    // output (macapp/mdpreview.py). Intentionally NOT run through escHtml —
    // re-escaping would show the tags as text. Do not "fix" by wrapping.
    $('preview-title').textContent = baseName(path);
    $('preview-body').innerHTML = html;
    $('preview-body').scrollTop = 0;
    $('preview-overlay').classList.add('visible');
  });
}

$('btn-preview-close').addEventListener('click', function () {
  $('preview-overlay').classList.remove('visible');
});
$('preview-overlay').addEventListener('click', function (e) {
  if (e.target === this) this.classList.remove('visible');  // scrim click closes
});

/* ---------- About overlay ---------- */

$('btn-about').addEventListener('click', function () {
  $('about-overlay').classList.add('visible');
});
$('btn-about-close').addEventListener('click', function () {
  $('about-overlay').classList.remove('visible');
});
$('about-overlay').addEventListener('click', function (e) {
  if (e.target === this) this.classList.remove('visible');
});
$('btn-about-github').addEventListener('click', function () {
  pywebview.api.open_github();
});

/* ---------- Header actions ---------- */

$('btn-github').addEventListener('click', function () {
  pywebview.api.open_github();
});

$('btn-lang').addEventListener('click', function () {
  setLang(_lang === 'zh' ? 'en' : 'zh');
});

/* ---------- Keyboard: Esc closes the topmost overlay ---------- */

document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  ['preview-overlay', 'about-overlay'].some(function (id) {
    var el = $(id);
    if (el.classList.contains('visible')) {
      el.classList.remove('visible');
      return true;
    }
    return false;
  });
});
