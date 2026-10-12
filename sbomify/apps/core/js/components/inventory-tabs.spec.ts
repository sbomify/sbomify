import { afterEach, describe, expect, test } from 'bun:test';
import { inventoryTabs } from './inventory-tabs';

// The controller retitles the page; bun runs these without a DOM.
const page = globalThis as { document?: { title: string } };
page.document ??= { title: '' };

type RequestDetail = Parameters<ReturnType<typeof inventoryTabs>['begin']>[0]['detail'];
const event = (detail: RequestDetail) => ({ detail }) as CustomEvent<RequestDetail>;
const request = (kind: string, xhr: XMLHttpRequest) => event({
    elt: { dataset: { inventoryTab: kind } } as unknown as HTMLElement,
    target: { id: 'inventory-panel' } as HTMLElement,
    xhr,
});

const instances: ReturnType<typeof inventoryTabs>[] = [];
afterEach(() => { instances.splice(0).forEach(tabs => tabs.destroy?.()); });

const KINDS = ['products', 'releases', 'components'];
const heading = (kind: string) => kind.charAt(0).toUpperCase() + kind.slice(1);

function setup(kind = 'products') {
    const panel = { dataset: { inventoryKind: kind } };
    const links = KINDS.map(name => ({
        href: `/${name}/`,
        dataset: {
            inventoryTab: name,
            inventoryHeading: heading(name),
            inventorySubtitle: `Every ${name.slice(0, -1)} here.`,
            inventoryTitle: `${heading(name)} · sbomify`,
        },
    }));
    const tabs = Object.assign(inventoryTabs(), {
        $el: {
            querySelector: () => panel,
            querySelectorAll: () => links,
        } as unknown as HTMLElement,
    });
    tabs.init?.();
    instances.push(tabs);
    return { tabs, panel, links };
}

describe('inventory panel navigation', () => {
    test('history initializes from the restored panel instead of the original frame', () => {
        const { tabs } = setup('releases');
        expect(tabs.selectedKind).toBe('releases');
        expect(tabs.loading).toBe(false);
    });

    test('a late failure or swap cannot clear the latest selection', () => {
        const { tabs } = setup();
        const first = {} as XMLHttpRequest;
        const second = {} as XMLHttpRequest;
        tabs.begin(request('releases', first));
        tabs.begin(request('components', second));
        tabs.finish(event({ xhr: first, successful: false }));
        tabs.swapped(request('releases', first));
        expect(tabs.selectedKind).toBe('components');
        expect(tabs.loading).toBe(true);
        expect(tabs.failed).toBe(false);
    });

    test('a successful panel commits the new selection', () => {
        const { tabs, panel } = setup();
        const xhr = {} as XMLHttpRequest;
        tabs.begin(request('components', xhr));
        panel.dataset.inventoryKind = 'components';
        tabs.swapped(request('components', xhr));
        tabs.finish(event({ xhr, successful: true }));
        expect(tabs.loadedKind).toBe('components');
        expect(tabs.loading).toBe(false);
    });

    test('a failed request restores the loaded panel and permits retry', () => {
        const { tabs } = setup('releases');
        const xhr = {} as XMLHttpRequest;
        tabs.begin(request('components', xhr));
        tabs.finish(event({ xhr, successful: false }));
        expect(tabs.selectedKind).toBe('releases');
        expect(tabs.loading).toBe(false);
        expect(tabs.failed).toBe(true);
        tabs.begin(request('components', {} as XMLHttpRequest));
        expect(tabs.failed).toBe(false);
        expect(tabs.loading).toBe(true);
    });

    test('ordinary result updates do not activate the tab loader', () => {
        const { tabs } = setup();
        tabs.begin(event({ target: { id: 'inventory-content-results' } as HTMLElement, xhr: {} as XMLHttpRequest }));
        expect(tabs.loading).toBe(false);
    });

    test('background refresh cannot interrupt pending navigation', () => {
        const { tabs } = setup();
        let prevented = false;
        tabs.begin(request('releases', {} as XMLHttpRequest));
        tabs.confirm({ detail: { elt: tabs.$el }, preventDefault: () => { prevented = true; } } as CustomEvent<RequestDetail>);
        expect(prevented).toBe(true);
    });
});


describe('inventory headings follow the open tab', () => {
    test('the heading starts on the panel on screen, titling a restored one', () => {
        // Back restores a panel under whatever title the page was left with.
        document.title = 'Components · sbomify';
        const { tabs } = setup('releases');
        expect(tabs.heading).toBe('Releases');
        expect(tabs.headingSubtitle).toBe('Every release here.');
        expect(document.title).toBe('Releases · sbomify');
    });

    test('selecting a tab retitles the page before its panel arrives', () => {
        const { tabs, panel } = setup();
        const xhr = {} as XMLHttpRequest;
        tabs.begin(request('components', xhr));
        expect(tabs.heading).toBe('Components');
        expect(document.title).toBe('Components · sbomify');
        panel.dataset.inventoryKind = 'components';
        tabs.swapped(request('components', xhr));
        expect(tabs.heading).toBe('Components');
    });

    test('a failed tab restores the heading of the panel still on screen', () => {
        const { tabs } = setup('products');
        const xhr = {} as XMLHttpRequest;
        tabs.begin(request('releases', xhr));
        tabs.finish(event({ xhr, successful: false }));
        expect(tabs.heading).toBe('Products');
        expect(document.title).toBe('Products · sbomify');
    });
});


describe('debounced inventory skeleton', () => {
    test('selects immediately but only shows the skeleton for a slower request', async () => {
        const { tabs } = setup();
        tabs.begin(request('releases', {} as XMLHttpRequest));
        expect(tabs.selectedKind).toBe('releases');
        expect(tabs.loading).toBe(true);
        expect(tabs.showSkeleton).toBe(false);
        await new Promise(resolve => setTimeout(resolve, 250));
        expect(tabs.showSkeleton).toBe(true);
    });

    test('a fast swap cancels the pending skeleton', async () => {
        const { tabs, panel } = setup();
        const xhr = {} as XMLHttpRequest;
        tabs.begin(request('releases', xhr));
        panel.dataset.inventoryKind = 'releases';
        tabs.swapped(request('releases', xhr));
        await new Promise(resolve => setTimeout(resolve, 250));
        expect(tabs.showSkeleton).toBe(false);
        expect(tabs.loading).toBe(false);
    });

    test.each(['failure', 'destroy'])('%s cancels the pending skeleton', async reason => {
        const { tabs } = setup();
        const xhr = {} as XMLHttpRequest;
        tabs.begin(request('releases', xhr));
        if (reason === 'failure') tabs.finish(event({ xhr, successful: false }));
        else tabs.destroy?.();
        await new Promise(resolve => setTimeout(resolve, 250));
        expect(tabs.showSkeleton).toBe(false);
        expect(tabs.loadingTimer).toBeUndefined();
    });
});
