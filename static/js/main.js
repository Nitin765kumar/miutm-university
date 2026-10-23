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

  /* ---- Confirm dangerous actions ---------------------------------------- */
  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    // stop double submits
    var btn = e.target.querySelector && e.target.querySelector('[data-once]');
    if (btn && !e.defaultPrevented) {
      btn.setAttribute('aria-busy', 'true');
      setTimeout(function () { btn.disabled = true; }, 0);
    }
  });
  window.addEventListener('pageshow', function () {
    $$('[data-once]').forEach(function (b) { b.disabled = false; b.removeAttribute('aria-busy'); });
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
})();
