// Copy buttons: <button data-copy="text"> or <button data-copy-from="#elementId">
document.addEventListener('click', function (e) {
  var btn = e.target.closest('[data-copy], [data-copy-from]');
  if (!btn) return;
  var text = btn.getAttribute('data-copy');
  if (text === null) {
    var src = document.querySelector(btn.getAttribute('data-copy-from'));
    text = src ? (src.value !== undefined && src.tagName === 'INPUT' ? src.value : src.textContent) : '';
  }
  text = (text || '').trim();
  var done = function () {
    var old = btn.getAttribute('data-label') || btn.textContent;
    btn.setAttribute('data-label', old);
    btn.textContent = 'Copied';
    setTimeout(function () { btn.textContent = old; }, 1400);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, function () { fallback(text, done); });
  } else {
    fallback(text, done);
  }
});
function fallback(text, done) {
  var ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch (err) { /* ignore */ }
  document.body.removeChild(ta);
}

// Language tabs: <div data-tabs> with buttons[data-tab] and panels[data-panel]
document.querySelectorAll('[data-tabs]').forEach(function (group) {
  var buttons = group.querySelectorAll('[data-tab]');
  var panels = group.querySelectorAll('[data-panel]');
  function show(name) {
    buttons.forEach(function (b) { b.setAttribute('aria-selected', b.dataset.tab === name ? 'true' : 'false'); });
    panels.forEach(function (p) { p.classList.toggle('hide', p.dataset.panel !== name); });
    try { localStorage.setItem('pg-lang', name); } catch (err) { /* ignore */ }
  }
  buttons.forEach(function (b) { b.addEventListener('click', function () { show(b.dataset.tab); }); });
  var saved = null;
  try { saved = localStorage.getItem('pg-lang'); } catch (err) { /* ignore */ }
  var has = Array.prototype.some.call(buttons, function (b) { return b.dataset.tab === saved; });
  show(has ? saved : buttons[0].dataset.tab);
});

// Open the provider card named in the URL hash (e.g. #razorpay)
if (location.hash) {
  var target = document.querySelector(location.hash);
  if (target && target.tagName === 'DETAILS') target.open = true;
}
