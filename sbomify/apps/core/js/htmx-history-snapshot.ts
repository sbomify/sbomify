/**
 * Keeps the nodes Alpine renders out of HTMX's history snapshots.
 *
 * HTMX saves a page for Back by serialising the live body. That includes what
 * Alpine rendered from a `<template>`: `x-teleport`'s dialogs and menus moved
 * to the end of the body, `x-for`'s clones, `x-if`'s element. On restore the
 * templates come back too and Alpine renders them again, but the old copies are
 * now plain markup with no link to the component they were rendered from, so
 * Alpine initialises them on their own and every binding in them throws: the
 * confirm dialog's `title`, a menu's `open` (which resolves to `window.open`),
 * the theme switcher's `option`.
 *
 * Marking those nodes just before the snapshot is taken, and dropping marked
 * nodes when it is restored, leaves the templates to render afresh.
 */

export const RENDERED_ATTRIBUTE = 'data-alpine-rendered';

/** The properties Alpine leaves on a `<template>` pointing at what it rendered. */
export interface AlpineTemplate {
    _x_teleport?: Element;
    _x_lookup?: Map<unknown, Element>;
    _x_currentIfEl?: Element;
}

interface HistoryCacheHitDetail {
    item?: { content?: string };
}

/** Every element an Alpine template directive has rendered, outermost or not. */
export function renderedByTemplates(templates: Iterable<AlpineTemplate>): Element[] {
    const rendered: Element[] = [];
    for (const template of templates) {
        if (template._x_teleport) rendered.push(template._x_teleport);
        if (template._x_currentIfEl) rendered.push(template._x_currentIfEl);
        template._x_lookup?.forEach(clone => rendered.push(clone));
    }
    return rendered;
}

function stripRendered(html: string): string {
    const holder = document.createElement('template');
    holder.innerHTML = html;
    holder.content.querySelectorAll(`[${RENDERED_ATTRIBUTE}]`).forEach(el => el.remove());
    return holder.innerHTML;
}

export function registerHistorySnapshotCleanup(): void {
    document.body.addEventListener('htmx:beforeHistorySave', () => {
        const templates = document.querySelectorAll('template') as unknown as Iterable<AlpineTemplate>;
        const rendered = renderedByTemplates(templates);
        rendered.forEach(el => el.setAttribute(RENDERED_ATTRIBUTE, ''));
        // HTMX serialises the page synchronously after this event, so the
        // marks only need to last until the current task finishes.
        queueMicrotask(() => rendered.forEach(el => el.removeAttribute(RENDERED_ATTRIBUTE)));
    });

    document.body.addEventListener('htmx:historyCacheHit', (event: Event) => {
        const item = (event as CustomEvent<HistoryCacheHitDetail>).detail?.item;
        if (item?.content) item.content = stripRendered(item.content);
    });
}
