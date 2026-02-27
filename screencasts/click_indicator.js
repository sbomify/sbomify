// Click indicator for Playwright video recordings.
// Injected via context.add_init_script() — runs before every page load.
//
// Shows a bright dot at the cursor position and a ripple animation on click.
// Both use pointer-events:none so they never intercept real interactions.

(function installClickIndicator() {
  function ensureStyles() {
    if (document.getElementById('__click-indicator-styles')) return;
    var style = document.createElement('style');
    style.id = '__click-indicator-styles';
    style.textContent = [
      '@keyframes __click-ripple {',
      '  0%   { transform: translate(-50%, -50%) scale(0); opacity: 0.85; }',
      '  100% { transform: translate(-50%, -50%) scale(1); opacity: 0; }',
      '}',
      '.__click-indicator {',
      '  position: fixed;',
      '  width: 60px;',
      '  height: 60px;',
      '  border-radius: 50%;',
      '  background: rgba(255, 68, 68, 0.35);',
      '  border: 2.5px solid rgba(255, 50, 50, 0.6);',
      '  pointer-events: none;',
      '  z-index: 2147483647;',
      '  animation: __click-ripple 0.5s ease-out forwards;',
      '}',
      '.__cursor-dot {',
      '  position: fixed;',
      '  width: 20px;',
      '  height: 20px;',
      '  border-radius: 50%;',
      '  background: rgba(255, 60, 60, 0.75);',
      '  border: 2px solid rgba(220, 40, 40, 0.85);',
      '  box-shadow: 0 0 8px rgba(255, 50, 50, 0.5);',
      '  pointer-events: none;',
      '  z-index: 2147483647;',
      '  transform: translate(-50%, -50%);',
      '  transition: left 0.08s linear, top 0.08s linear;',
      '  display: none;',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  }

  function ensureCursorDot() {
    if (document.getElementById('__cursor-dot')) return;
    var dot = document.createElement('div');
    dot.id = '__cursor-dot';
    dot.className = '__cursor-dot';
    document.body.appendChild(dot);

    document.addEventListener('mousemove', function (e) {
      dot.style.display = 'block';
      dot.style.left = e.clientX + 'px';
      dot.style.top = e.clientY + 'px';
    }, true);
  }

  function onMouseDown(e) {
    ensureStyles();
    var ripple = document.createElement('div');
    ripple.className = '__click-indicator';
    ripple.style.left = e.clientX + 'px';
    ripple.style.top = e.clientY + 'px';
    document.body.appendChild(ripple);
    ripple.addEventListener('animationend', function () {
      ripple.remove();
    });
  }

  // Styles can be injected before body exists
  ensureStyles();

  if (document.body) {
    ensureCursorDot();
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      ensureCursorDot();
    });
  }

  document.addEventListener('mousedown', onMouseDown, true);
})();
