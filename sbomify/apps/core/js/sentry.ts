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
    sendDefaultPii: true,
  });
}

export { Sentry };
