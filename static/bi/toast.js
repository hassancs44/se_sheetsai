/**
 * SE_SHEETSAI — BI Toast notifications
 */
(function() {
  'use strict';
  var container = null;
  function ensureContainer() {
    if (container) return container;
    container = document.createElement('div');
    container.id = 'bi-toast-container';
    container.setAttribute('aria-live', 'polite');
    container.style.cssText = 'position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%);z-index:9999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
    document.body.appendChild(container);
    return container;
  }
  function show(message, type) {
    type = type || 'info';
    var el = document.createElement('div');
    el.className = 'bi-toast show ' + type;
    el.textContent = message;
    el.style.cssText = 'pointer-events:auto;padding:0.75rem 1.25rem;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);font-size:0.9rem;animation:bi-slide-up 0.25s ease;';
    ensureContainer().appendChild(el);
    setTimeout(function() {
      el.classList.remove('show');
      setTimeout(function() { el.remove(); }, 300);
    }, 3000);
  }
  window.BIToast = show;
})();
