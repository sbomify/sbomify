import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { initDjangoMessages, processDjangoMessages } from './django-messages';

interface Toast {
  title: string;
  message: string;
  type: string;
  duration: number;
}

const toasts: Toast[] = [];
const listeners = new Map<string, (event: Event) => void>();
const original = { window: globalThis.window, document: globalThis.document };

/** A page holding the hidden container messages.html.j2 renders, one span per level. */
function stubPage(levels: string[]): void {
  globalThis.window = {
    dispatchEvent: (event: CustomEvent<Toast>) => toasts.push(event.detail) > 0,
  } as unknown as Window & typeof globalThis;
  const container = {
    dataset: {},
    remove: () => {},
    querySelectorAll: () => levels.map(level => ({ dataset: { level }, textContent: `${level} message` })),
  };
  globalThis.document = {
    querySelectorAll: () => [container],
    body: { addEventListener: (name: string, listener: (event: Event) => void) => listeners.set(name, listener) },
  } as unknown as Document;
}

describe('django-messages', () => {
  beforeEach(() => {
    toasts.length = 0;
    listeners.clear();
  });

  afterEach(() => {
    globalThis.window = original.window;
    globalThis.document = original.document;
  });

  test.each([
    ['debug', 'info', 'Info'],
    ['info', 'info', 'Info'],
    ['success', 'success', 'Success'],
    ['warning', 'warning', 'Warning'],
    ['error', 'error', 'Error'],
    ['', 'info', 'Info'],
  ])('a rendered %p message shows a %s toast', (level, type, title) => {
    stubPage([level]);
    processDjangoMessages();
    expect(toasts).toEqual([{ title, message: `${level} message`, type, duration: 3000 }]);
  });

  test('the HTMX messages event takes the same types the server sends', () => {
    stubPage([]);
    initDjangoMessages();
    const types = ['success', 'error', 'warning', 'info'];
    listeners.get('messages')?.({
      detail: { value: types.map(type => ({ type, message: `${type} message` })) },
    } as unknown as Event);
    expect(toasts.map(toast => toast.type)).toEqual(types);
  });
});
