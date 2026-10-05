/**
 * A morph swap that leaves `hx-preserve` subtrees alone.
 *
 * htmx applies `hx-preserve` inside its own swap. An extension that implements
 * `handleSwap` replaces that step, and the vendored `alpine-morph` extension
 * calls `Alpine.morph(target, html)` with no options, so `hx-preserve` does
 * nothing under `hx-swap="morph"`.
 *
 * That matters wherever the server cannot know what the reader has already
 * loaded. The artifact page's assessment panels fetch their findings when a
 * reader first opens them, so a refresh response always carries the unopened
 * placeholder. Morphing it in would swap a table the reader had filtered and
 * paged for a spinner that never fetches again, because its `once` trigger has
 * already fired.
 *
 * This is registered under its own name rather than patched into the vendored
 * extension, which `bun run copy-deps` rewrites from node_modules on every
 * build. Opt in with `hx-ext="ignore:alpine-morph, morph-preserve"`: both
 * extensions claim the `morph` style, so the inherited one has to be turned
 * off or the swap runs twice.
 */

// The node-type values rather than the Node global, so the swap is
// exercisable outside a browser, the way the shared components already treat
// their timers.
const ELEMENT_NODE = 1;
const DOCUMENT_FRAGMENT_NODE = 11;

type Skip = () => void;

interface MorphOptions {
  updating: (el: Element, toEl: Element, childrenOnly: boolean, skip: Skip) => void;
}

interface AlpineWithMorph {
  morph: (el: Element, html: string | Element, options?: MorphOptions) => void;
}

interface HtmxExtension {
  isInlineSwap: (swapStyle: string) => boolean;
  handleSwap: (swapStyle: string, target: Element, fragment: Node) => Element[] | false;
}

interface HtmxLike {
  defineExtension: (name: string, ext: HtmxExtension) => void;
}

export const EXTENSION_NAME = 'morph-preserve';

/** The swap itself, exported so it can be exercised without htmx or a browser. */
export function morphPreservingMarkedSubtrees(
  alpine: AlpineWithMorph,
  target: Element,
  fragment: Node
): Element[] | false {
  const incoming =
    fragment.nodeType === DOCUMENT_FRAGMENT_NODE
      ? (fragment as DocumentFragment).firstElementChild
      : (fragment as Element);
  if (!incoming) return false;

  alpine.morph(target, incoming.outerHTML, {
    updating: (el, _toEl, _childrenOnly, skip) => {
      // The guard is for text nodes, which have no attributes.
      if (el.nodeType === ELEMENT_NODE && el.hasAttribute('hx-preserve')) {
        skip();
      }
    },
  });

  return [target];
}

export function registerMorphPreserve(): void {
  // Cast through unknown: window.Alpine is globally typed as Alpine, whose
  // published type does not carry the morph plugin's method.
  const scope = window as unknown as { htmx?: HtmxLike };
  const engine = scope.htmx;
  if (!engine) return;

  engine.defineExtension(EXTENSION_NAME, {
    isInlineSwap: (swapStyle) => swapStyle === 'morph',
    handleSwap: (swapStyle, target, fragment) => {
      // Alpine is resolved per swap, not at registration: this module loads
      // from the same bundle that starts Alpine, and the order is not ours.
      const alpine = (window as unknown as { Alpine?: AlpineWithMorph }).Alpine;
      if (swapStyle !== 'morph' || !alpine) return false;
      return morphPreservingMarkedSubtrees(alpine, target, fragment);
    },
  });
}
