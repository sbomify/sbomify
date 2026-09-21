/**
 * Charts for the ops dashboard.
 *
 * Every series arrives as JSON in a data attribute rather than as values
 * pasted into a script body, which is both safer and the only way workspace
 * names survive: Django escapes an apostrophe to &#x27; and a script element
 * does not decode entities, so an interpolated label renders the entity.
 */

import type { Chart, ChartConfiguration } from 'chart.js';

const charts = new WeakMap<HTMLCanvasElement, Chart>();

function readNumbers(canvas: HTMLCanvasElement, attribute: string): number[] {
  const raw = canvas.dataset[attribute];
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(Number) : [];
  } catch {
    return [];
  }
}

function readStrings(canvas: HTMLCanvasElement, attribute: string): string[] {
  const raw = canvas.dataset[attribute];
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function cssToken(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!value) return fallback;
  // Tokens are stored as space-separated channels, e.g. "37 41 63".
  return /^[\d\s.]+$/.test(value) ? `rgb(${value.replace(/\s+/g, ' ')})` : value;
}

function shortDate(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function signupsConfig(canvas: HTMLCanvasElement): ChartConfiguration {
  const accent = cssToken('--color-primary', '#4263EB');
  return {
    type: 'line',
    data: {
      labels: readStrings(canvas, 'labels').map(shortDate),
      datasets: [
        {
          label: 'Signups',
          data: readNumbers(canvas, 'values'),
          borderColor: accent,
          backgroundColor: accent,
          fill: false,
          tension: 0.25,
          pointRadius: 0,
          pointHitRadius: 12,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  };
}

function plansConfig(canvas: HTMLCanvasElement): ChartConfiguration {
  const accent = cssToken('--color-primary', '#4263EB');
  return {
    type: 'bar',
    data: {
      labels: readStrings(canvas, 'labels'),
      datasets: [
        {
          label: 'Workspaces',
          data: readNumbers(canvas, 'values'),
          backgroundColor: accent,
          borderRadius: 4,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  };
}

export function initOpsCharts(root: ParentNode = document): void {
  if (typeof window.Chart === 'undefined') return;

  root.querySelectorAll<HTMLCanvasElement>('canvas.ops-chart').forEach((canvas) => {
    const existing = charts.get(canvas);
    if (existing) {
      existing.destroy();
      charts.delete(canvas);
    }

    const kind = canvas.dataset.chart;
    const config = kind === 'signups' ? signupsConfig(canvas) : kind === 'plans' ? plansConfig(canvas) : null;
    if (!config) return;

    charts.set(canvas, new window.Chart(canvas, config));
  });
}
