// Camera-paced scrolling.
//
// Chromium's own `behavior: 'smooth'` runs a pan in roughly 300-500ms. The
// recorder captures 12-16 unique frames a second (a CDP screencast throttle,
// not rasterisation — rendering at half the pixel count does not move it), so
// a whole page pan lands in five to eight frames and reads as a stutter.
//
// Overriding the API rather than editing 60-odd call sites also covers the
// scrolls the app itself performs, which the recording has no other way to
// reach. Duration is a global so a recording can slow a particular pan further.
//
// Only root-scroller pans are taken over. An element inside its own scrolling
// container is delegated to the native implementation, because the arithmetic
// below assumes the document is what moves.
(() => {
  if (window.__sbomifyScrollPatched) return;
  window.__sbomifyScrollPatched = true;

  window.__sbomifyScrollDuration = 1400;

  const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  const scrollableAncestor = (el) => {
    for (let node = el.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      const overflowY = style.overflowY;
      if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
        return node;
      }
    }
    return null;
  };

  // Stop whatever pan is in flight, so a caller can take the scroll position
  // over deterministically.
  window.__sbomifyCancelScroll = () => {
    window.__sbomifyScrollToken = (window.__sbomifyScrollToken || 0) + 1;
  };

  const nativeScrollIntoView = Element.prototype.scrollIntoView;

  Element.prototype.scrollIntoView = function (options) {
    const smooth = options && typeof options === 'object' && options.behavior === 'smooth';
    if (!smooth || scrollableAncestor(this)) {
      return nativeScrollIntoView.call(this, options);
    }

    const scroller = document.scrollingElement || document.documentElement;
    const rect = this.getBoundingClientRect();
    const block = options.block || 'start';

    let delta;
    if (block === 'center') {
      delta = rect.top - (window.innerHeight - rect.height) / 2;
    } else if (block === 'end') {
      delta = rect.bottom - window.innerHeight;
    } else {
      delta = rect.top;
    }

    const from = scroller.scrollTop;
    const max = scroller.scrollHeight - window.innerHeight;
    const to = Math.max(0, Math.min(max, from + delta));
    if (Math.abs(to - from) < 2) return;

    const duration = window.__sbomifyScrollDuration;
    const started = performance.now();

    // Each pan supersedes the last, and anything else may cancel the current
    // one. Without this the loop keeps assigning scrollTop from its own
    // progress every frame, so a direct scroll correction elsewhere is undone
    // on the very next frame — which is exactly what made the trust-centre
    // field impossible to hold in view, and why it looked like plain scrolling
    // was broken.
    const token = (window.__sbomifyScrollToken = (window.__sbomifyScrollToken || 0) + 1);

    const step = (now) => {
      if (window.__sbomifyScrollToken !== token) return;
      const t = Math.min(1, (now - started) / duration);
      scroller.scrollTop = from + (to - from) * easeInOutCubic(t);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
})();
