import * as Sentry from "@sentry/browser";

declare global {
  interface Window {
    __SENTRY_CONFIG__?: {
      dsn: string;
      release: string;
    };
  }
}

export function initSentry(): void {
  const config = window.__SENTRY_CONFIG__;

  if (!config?.dsn) {
    return; // Sentry disabled if no DSN provided
  }

  Sentry.init({
    dsn: config.dsn,
    release: config.release || undefined,
    // v11 replaced `sendDefaultPii` with per-category `dataCollection`. Every
    // category defaults to permissive when `dataCollection` is supplied, so
    // this reproduces `sendDefaultPii: true` while naming the one that matters
    // in the browser.
    dataCollection: { userInfo: true },
  });
}

export { Sentry };
