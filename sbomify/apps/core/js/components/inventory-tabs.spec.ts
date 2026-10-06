import { afterEach, describe, expect, test } from 'bun:test';
import { inventoryTabs } from './inventory-tabs';

type RequestDetail = Parameters<ReturnType<typeof inventoryTabs>['begin']>[0]['detail'];
const event = (detail: RequestDetail) => ({ detail }) as CustomEvent<RequestDetail>;
const request = (kind: string, xhr: XMLHttpRequest) => event({
    elt: { dataset: { inventoryTab: kind } } as unknown as HTMLElement,
    target: { id: 'inventory-panel' } as HTMLElement,
    xhr,
});

const instances: ReturnType<typeof inventoryTabs>[] = [];
afterEach(() => { instances.splice(0).forEach(tabs => tabs.destroy?.()); });

function setup(kind = 'products') {
    const panel = { dataset: { inventoryKind: kind } };
    const tabs = Object.assign(inventoryTabs(), {
        $el: { querySelector: () => panel } as unknown as HTMLElement,
    });
    tabs.init?.();
    instances.push(tabs);
    return { tabs, panel };
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
