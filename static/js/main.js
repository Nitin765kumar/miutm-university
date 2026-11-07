/* MIUTM v2 - small, dependency-free enhancements. Every feature works without JavaScript
   (forms submit, lists show everything); this file only makes things nicer. */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ---- Mobile navigation ------------------------------------------------ */
  var toggle = $('.nav-toggle');
  var nav = $('#site-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('is-open')) {
        nav.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
      }
    });
  }

  /* ---- Home: programme finder ------------------------------------------- */
  var finder = $('[data-finder]');
  if (finder) {
    var items = $$('.finder-list li', finder);
    var count = $('.finder-count', finder);
    var empty = $('.finder-empty', finder);

    var update = function () {
      var stage = ($('input[name="stage"]:checked', finder) || {}).value;
      $$('[data-sub]', finder).forEach(function (fs) { fs.hidden = fs.getAttribute('data-sub') !== stage; });
      var sub = stage === 'short' ? '' : (($('[data-sub="' + stage + '"] input:checked', finder) || {}).value || '');
      var token = stage === '12' ? 's12' + sub : stage === 'degree' ? (sub === 'c' ? 'gcs' : 'gany') : 'short';
      var shown = 0;
      items.forEach(function (li) {
        var match = li.getAttribute('data-aud').split(' ').indexOf(token) !== -1;
        li.hidden = !match;
        if (match) { shown += 1; }
      });
      count.textContent = shown === 1 ? '1 programme you can apply to' : shown + ' programmes you can apply to';
      if (empty) { empty.hidden = shown !== 0; }
    };
    finder.addEventListener('change', update);
    update();
  }

  /* ---- Programmes page: search and filter ------------------------------- */
  var list = $('[data-filter-list]');
  if (list) {
    var rows = $$('li[data-text]', list);
    var q = $('#prog-q');
    var school = $('#prog-school');
    var status = $('#prog-count');
    var none = $('#prog-none');

    var apply = function () {
      var term = (q.value || '').trim().toLowerCase();
      var level = ($('input[name="level"]:checked') || {}).value || '';
      var sch = school.value;
      var shown = 0;
      rows.forEach(function (li) {
        var ok = (!term || li.getAttribute('data-text').indexOf(term) !== -1) &&
                 (!level || li.getAttribute('data-level') === level) &&
                 (!sch || li.getAttribute('data-school') === sch);
        li.hidden = !ok;
        if (ok) { shown += 1; }
      });
      status.textContent = shown + (shown === 1 ? ' programme' : ' programmes');
      none.hidden = shown !== 0;
    };
    q.addEventListener('input', apply);
    school.addEventListener('change', apply);
    $$('input[name="level"]').forEach(function (r) { r.addEventListener('change', apply); });
    apply();
  }

  /* ---- Application form: step by step ----------------------------------- */
  var wizard = $('[data-wizard]');
  if (wizard) {
    var steps = $$('.step', wizard);
    var marks = $$('.stepper li');
    var submit = $('[data-submit]', wizard);
    var prevBtn = $('[data-prev]', wizard), nextBtn = $('[data-next]', wizard);
    var stepInput = $('input[name="step"]', wizard);
    var current = 0;

    var show = function (n, focus) {
      current = Math.max(0, Math.min(steps.length - 1, n));
      steps.forEach(function (s, i) { s.hidden = i !== current; });
      marks.forEach(function (m, i) {
        m.setAttribute('data-state', i < current ? 'done' : i === current ? 'current' : 'next');
        if (i === current) { m.setAttribute('aria-current', 'step'); } else { m.removeAttribute('aria-current'); }
      });
      if (submit) { submit.hidden = current !== steps.length - 1; }
      if (prevBtn) { prevBtn.hidden = current === 0; }
      if (nextBtn) { nextBtn.hidden = current === steps.length - 1; }
      if (stepInput) { stepInput.value = String(current); }
      if (focus) {
        var lg = $('legend', steps[current]);
        if (lg) { lg.setAttribute('tabindex', '-1'); lg.focus(); }
        wizard.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }
    };

    var validStep = function () {
      var controls = $$('input, select, textarea', steps[current]);
      for (var i = 0; i < controls.length; i++) {
        if (!controls[i].checkValidity()) { controls[i].reportValidity(); return false; }
      }
      return true;
    };

    wizard.addEventListener('click', function (e) {
      var next = e.target.closest('[data-next]');
      var prev = e.target.closest('[data-prev]');
      if (next && validStep()) { show(current + 1, true); }
      if (prev) { show(current - 1, true); }
    });

    // open on the step with a server-side error, otherwise on the step we were on
    var firstBad = steps.findIndex(function (s) { return $('[data-invalid]', s); });
    var wanted = parseInt(wizard.getAttribute('data-start'), 10) || 0;
    show(firstBad >= 0 ? firstBad : wanted, false);
  }

  /* ---- "Leave without saving?" on Cancel links ---------------------------- */
  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-leave]');
    if (link && !window.confirm(link.getAttribute('data-leave'))) { e.preventDefault(); }
  });

  /* ---- Confirm dangerous actions, and stop double submits ------------------ */
  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    var btn = e.target.querySelector && e.target.querySelector('[data-once]');
    if (btn && !e.defaultPrevented) {
      btn.setAttribute('aria-busy', 'true');
      btn.setAttribute('data-label', btn.textContent);
      btn.textContent = btn.getAttribute('data-loading') || 'Please wait...';
      setTimeout(function () { btn.disabled = true; }, 0);
    }
  });
  window.addEventListener('pageshow', function () {
    $$('[data-once]').forEach(function (b) {
      b.disabled = false; b.removeAttribute('aria-busy');
      if (b.getAttribute('data-label')) { b.textContent = b.getAttribute('data-label'); }
    });
  });

  /* ---- Copy / print buttons --------------------------------------------- */
  document.addEventListener('click', function (e) {
    var copy = e.target.closest('[data-copy]');
    if (copy) {
      var text = copy.getAttribute('data-copy');
      var done = function () {
        var old = copy.querySelector('span');
        if (old) { var was = old.textContent; old.textContent = 'Copied'; setTimeout(function () { old.textContent = was; }, 1800); }
      };
      if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done); }
    }
    if (e.target.closest('[data-print]')) { window.print(); }
  });

  /* ---- Password fields: show/hide, strength, and matching ------------------- */
  var NS = 'http://www.w3.org/2000/svg';
  var eye = function (off) {
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true');
    var p = document.createElementNS(NS, 'path');
    p.setAttribute('d', off ? 'M3 3l18 18M10.6 6.2A10 10 0 0112 6c6 0 10 6 10 6a17 17 0 01-3.2 3.9M6.1 7.3A17 17 0 002 12s4 7 10 7a10 10 0 004.2-.9M9.9 9.9a3 3 0 004.2 4.2'
                      : 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 100 6 3 3 0 000-6z');
    svg.appendChild(p);
    return svg;
  };
  $$('input[type="password"]').forEach(function (input) {
    var wrap = document.createElement('div');
    wrap.className = 'pw-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'pw-toggle';
    btn.setAttribute('aria-label', 'Show password'); btn.setAttribute('aria-pressed', 'false');
    btn.appendChild(eye(false));
    btn.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      btn.setAttribute('aria-pressed', String(show));
      btn.replaceChild(eye(show), btn.firstChild);
    });
    wrap.appendChild(btn);
  });

  $$('input[data-strength]').forEach(function (input) {
    var min = parseInt(input.getAttribute('minlength'), 10) || 8;
    var box = document.createElement('div');
    box.className = 'pw-meter';
    box.innerHTML = '<div class="pw-bar" aria-hidden="true"><span></span></div><p class="pw-label" aria-live="polite"></p><ul class="pw-rules"></ul>';
    input.closest('.field').appendChild(box);
    var bar = $('.pw-bar span', box), label = $('.pw-label', box), list = $('.pw-rules', box);
    var rules = [
      ['At least ' + min + ' characters', function (v) { return v.length >= min; }],
      ['An upper case letter', function (v) { return /[A-Z]/.test(v); }],
      ['A lower case letter', function (v) { return /[a-z]/.test(v); }],
      ['A number', function (v) { return /[0-9]/.test(v); }],
      ['A special character (recommended)', function (v) { return /[^A-Za-z0-9]/.test(v); }]
    ];
    var update = function () {
      var v = input.value, met = rules.map(function (r) { return r[1](v); });
      list.textContent = '';
      rules.forEach(function (r, i) {
        var li = document.createElement('li');
        li.className = met[i] ? 'ok' : '';
        li.textContent = (met[i] ? '\u2713 ' : '\u25CB ') + r[0];
        list.appendChild(li);
      });
      var required = met[0] && met[1] && met[2] && met[3];
      var level = !v ? 0 : required && (met[4] || v.length >= 12) ? 3 : required ? 2 : 1;
      bar.className = 'lv' + level;
      label.textContent = v ? ['', 'Weak', 'Medium', 'Strong'][level] : '';
    };
    input.addEventListener('input', update);
    update();
  });

  $$('input[data-match]').forEach(function (input) {
    var other = $(input.getAttribute('data-match'));
    if (!other) { return; }
    var msg = document.createElement('p');
    msg.className = 'error js-match'; msg.setAttribute('role', 'status'); msg.hidden = true;
    msg.textContent = 'Passwords do not match.';
    input.closest('.field').appendChild(msg);
    var check = function () {
      var bad = input.value !== '' && input.value !== other.value;
      msg.hidden = !bad;
      input.setCustomValidity(bad ? 'Passwords do not match.' : '');
    };
    input.addEventListener('input', check); other.addEventListener('input', check);
  });

  /* ---- Friendly inline messages on every form ------------------------------- */
  var friendly = function (el) {
    var v = el.validity;
    if (v.valueMissing) { return el.type === 'checkbox' ? 'Please tick this box to continue.' : el.tagName === 'SELECT' ? 'Please choose an option.' : 'Please fill in this field.'; }
    if (v.typeMismatch) { return el.type === 'email' ? 'Please enter a valid email address, like name@example.com.' : 'Please enter a valid value.'; }
    if (v.patternMismatch) { return el.getAttribute('title') || 'Please match the format asked for.'; }
    if (v.tooShort) { return 'Please use at least ' + el.getAttribute('minlength') + ' characters.'; }
    if (v.rangeUnderflow || v.rangeOverflow) { return 'Please enter a value between ' + el.getAttribute('min') + ' and ' + el.getAttribute('max') + '.'; }
    if (v.customError) { return el.validationMessage; }
    return '';
  };
  var showError = function (el, text) {
    var field = el.closest('.field'); if (!field) { return; }
    var p = $('.js-error', field);
    if (!text) { if (p) { p.remove(); } el.removeAttribute('aria-invalid'); return; }
    if (!p) { p = document.createElement('p'); p.className = 'error js-error'; field.appendChild(p); }
    p.textContent = text; el.setAttribute('aria-invalid', 'true');
  };
  document.addEventListener('invalid', function (e) {
    var el = e.target;
    if (el.willValidate && !el.validity.customError) { el.setCustomValidity(friendly(el)); }
    showError(el, friendly(el) || el.validationMessage);
    if (!el.validity.customError || el.validationMessage === friendly(el)) { setTimeout(function () { el.setCustomValidity(''); }, 0); }
  }, true);
  document.addEventListener('blur', function (e) {
    var el = e.target;
    if (el.matches && el.matches('input, select, textarea') && el.type !== 'file' && el.form && el.form.hasAttribute('data-wizard') === false) {
      showError(el, el.checkValidity() ? '' : friendly(el));
    }
  }, true);
  document.addEventListener('input', function (e) {
    var el = e.target;
    if (el.matches && el.matches('input, select, textarea')) { if (!el.validity.customError) { el.setCustomValidity(''); } if ($('.js-error', el.closest('.field') || document.body) && el.checkValidity()) { showError(el, ''); } }
  });

  /* ---- Character counters and file checks ----------------------------------- */
  $$('textarea[maxlength]').forEach(function (t) {
    var c = document.createElement('p'); c.className = 'counter'; c.setAttribute('aria-hidden', 'true');
    t.closest('.field').appendChild(c);
    var u = function () { c.textContent = t.value.length + ' / ' + t.getAttribute('maxlength'); };
    t.addEventListener('input', u); u();
  });
  $$('input[type="file"]').forEach(function (input) {
    input.addEventListener('change', function () {
      var f = input.files && input.files[0]; if (!f) { showError(input, ''); return; }
      var max = (parseFloat(input.getAttribute('data-maxmb')) || 2) * 1024 * 1024;
      var ok = /\.(pdf|jpe?g|png)$/i.test(f.name);
      if (!ok) { showError(input, 'Only PDF, JPG and PNG files are accepted.'); input.value = ''; }
      else if (f.size > max) { showError(input, 'That file is ' + (f.size / 1048576).toFixed(1) + ' MB. The limit is ' + (max / 1048576) + ' MB.'); input.value = ''; }
      else { showError(input, ''); }
    });
  });

  /* ---- Bulk selection in the staff lists ------------------------------------ */
  $$('[data-select-all]').forEach(function (box) {
    box.addEventListener('change', function () {
      $$('input[name="ids"]', $(box.getAttribute('data-select-all'))).forEach(function (c) { c.checked = box.checked; });
    });
  });
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-confirm-bulk]'); if (!btn) { return; }
    var form = btn.form, action = form.elements.action.value;
    var n = $$('input[name="ids"]:checked', form).length;
    if (!n) { e.preventDefault(); window.alert('Tick at least one application first.'); return; }
    if (!action) { e.preventDefault(); window.alert('Choose what to do with the selected applications.'); form.elements.action.focus(); return; }
    var what = action === 'status' ? 'change the status of' : action === 'verify_docs' ? 'verify the pending documents of' : 'export';
    if (action !== 'export' && !window.confirm('Really ' + what + ' ' + n + ' application' + (n === 1 ? '' : 's') + '?')) { e.preventDefault(); }
  });
})();
