import { afterAll, afterEach, describe, expect, test } from 'bun:test';
import { scrollableTabs } from './scrollable-tabs';

// bun runs these without a DOM, so the element and the observers are stand-ins.
class FakeElement {
    scrollWidth = 0;
    scrollLeft = 0;
    clientWidth = 0;
    querySelector() { return null; }
    contains() { return false; }
}

const observed: unknown[] = [];

class FakeResizeObserver {
    observe(target: unknown) {
        if (!(target instanceof FakeElement)) throw new TypeError('target must be an Element');
        observed.push(target);
    }
    disconnect() {}
}

class FakeMutationObserver {
    observe() {}
    disconnect() {}
}

// Other specs read these globals, so they go back to how this file found them.
const scope = globalThis as Record<string, unknown>;
const stubs = { HTMLElement: FakeElement, ResizeObserver: FakeResizeObserver, MutationObserver: FakeMutationObserver };
const originals = Object.fromEntries(Object.keys(stubs).map(name => [name, scope[name]]));
Object.assign(scope, stubs);
afterAll(() => {
    for (const [name, value] of Object.entries(originals)) {
        if (value === undefined) delete scope[name];
        else scope[name] = value;
    }
});

const instances: ReturnType<typeof scrollableTabs>[] = [];
afterEach(() => {
    instances.splice(0).forEach(tabs => tabs.destroy?.());
    observed.splice(0);
});

function setup(refs: Record<string, unknown>) {
    const ticks: (() => void)[] = [];
    const tabs = Object.assign(scrollableTabs(), {
        $root: new FakeElement() as unknown as HTMLElement,
        $refs: refs,
        $nextTick: (callback: () => void) => { ticks.push(callback); },
    });
    instances.push(tabs);
    return { tabs, ticks };
}

describe('scrollable tabs', () => {
    test('observes the row once a morph has put it in place', () => {
        const refs: Record<string, unknown> = {};
        const { tabs, ticks } = setup(refs);

        expect(() => tabs.init?.()).not.toThrow();
        expect(observed).toHaveLength(0);

        refs.scroller = new FakeElement();
        refs.tabItems = new FakeElement();
        ticks.splice(0).forEach(tick => tick());
        expect(observed).toEqual([tabs.$root, refs.scroller, refs.tabItems]);
    });

    test('stays inert when the row never arrives', () => {
        const { tabs, ticks } = setup({});

        tabs.init?.();
        ticks.splice(0).forEach(tick => tick());
        expect(ticks).toHaveLength(0);
        expect(observed).toHaveLength(0);
        expect(() => tabs.measure()).not.toThrow();
        expect(() => tabs.revealActive()).not.toThrow();
        expect(tabs.overflow).toBe(false);
    });

    test('measures overflow when the row is there from the start', () => {
        const scroller = Object.assign(new FakeElement(), { scrollWidth: 400, clientWidth: 200 });
        const { tabs } = setup({ scroller, tabItems: new FakeElement() });

        tabs.init?.();
        tabs.measure();
        expect(observed).toHaveLength(3);
        expect(tabs.overflow).toBe(true);
        expect(tabs.canScrollForward).toBe(true);
    });
});
