/**
 * Spotlight search for the navbar.
 *
 * Navigation first: the endpoint returns a flat, ranked `results` list where
 * app destinations (settings, tokens, wizards) outrank the workspace's own
 * records. Rendering groups that list by section, so a section appears once
 * even if its members are not contiguous in the ranking — order *within* a
 * section is the server's, and a section's position follows its best-ranked
 * member. Nothing is re-scored here; ranking stays a server-side concern.
 *
 * Markup is Tailwind utilities matching the header's own dropdown. The
 * previous `search-result-*` class names pointed at layout.css, which the
 * Tailwind migration dropped from the pipeline — every rule was dead, which
 * is why the rows rendered unstyled with the chevron wrapping onto its own
 * line.
 *
 * Arrow keys, Enter and Escape work because a palette nobody can drive from
 * the keyboard is not a palette.
 */

interface SpotlightResult {
  title: string;
  url: string;
  section: string;
  section_label: string;
  icon: string;
  score: number;
}

interface SearchResponse {
  results?: SpotlightResult[];
}

let searchTimeout: ReturnType<typeof setTimeout> | null = null;
let currentSearchQuery = '';
let activeIndex = -1;
let activeResults: SpotlightResult[] = [];

function debounceSearch(callback: () => void, delay: number = 200): void {
  if (searchTimeout) clearTimeout(searchTimeout);
  searchTimeout = setTimeout(callback, delay);
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  // textContent -> innerHTML escapes <, > and &, but leaves quotes alone, so
  // the result is only safe between tags. These values are interpolated into
  // href="..." too, where an unescaped quote would end the attribute.
  return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * Group results by section while keeping the server's ranking.
 *
 * Sections appear in the order their best-ranked member did, and each
 * section appears exactly once — walking the flat list and emitting a header
 * on every change produced "Go to" twice when a lower-ranked navigate result
 * trailed a settings one. Returns the regrouped flat order too, so keyboard
 * indices match what is on screen.
 */
function groupBySection(results: SpotlightResult[]): { sections: SpotlightResult[][]; flat: SpotlightResult[] } {
  const bySection = new Map<string, SpotlightResult[]>();
  for (const result of results) {
    const bucket = bySection.get(result.section);
    if (bucket) bucket.push(result);
    else bySection.set(result.section, [result]);
  }
  const sections = [...bySection.values()];
  return { sections, flat: sections.flat() };
}

function renderResults(results: SpotlightResult[], query: string): string {
  if (!results.length) {
    return `<p class="px-4 py-6 text-center text-sm text-text-muted m-0">No results for "${escapeHtml(query)}"</p>`;
  }

  let html = '';
  let index = 0;

  for (const section of groupBySection(results).sections) {
    html += `<div class="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-text-muted">${escapeHtml(
      section[0].section_label
    )}</div>`;
    for (const result of section) {
      html += `
        <a href="${escapeHtml(result.url)}"
           class="spotlight-item group flex items-center gap-3 px-4 py-2.5 text-sm text-text no-underline transition-colors hover:bg-background"
           role="option"
           data-index="${index}">
          <i class="fas ${escapeHtml(result.icon)} w-4 shrink-0 text-center text-text-muted"></i>
          <span class="flex-1 min-w-0 truncate">${escapeHtml(result.title)}</span>
          <span class="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-text-muted opacity-0 group-[.is-active]:opacity-100">enter</span>
        </a>
      `;
      index += 1;
    }
  }

  return html;
}

function highlightActive(dropdown: HTMLElement): void {
  dropdown.querySelectorAll('.spotlight-item').forEach((el, i) => {
    const active = i === activeIndex;
    // The class drives the "enter" hint via group-[.is-active]; the
    // background is toggled alongside it so keyboard selection and hover
    // look identical — Tailwind has no hover-equivalent for "selected".
    el.classList.toggle('is-active', active);
    el.classList.toggle('bg-background', active);
    el.setAttribute('aria-selected', String(active));
    if (active) el.scrollIntoView({ block: 'nearest' });
  });
}

async function performSearch(query: string): Promise<void> {
  const dropdown = document.getElementById('search-results-dropdown');
  // The dropdown is a flush panel that owns overflow, so results render into
  // the inner list element, which carries the scroll cap.
  const list = document.getElementById('search-results-list');
  if (!dropdown || !list) return;

  if (query.length < 2) {
    dropdown.style.display = 'none';
    activeResults = [];
    activeIndex = -1;
    return;
  }

  currentSearchQuery = query;

  try {
    const response = await fetch(`/search/?${new URLSearchParams({ q: query, limit: '10' })}`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    // A session that expired while the dropdown was open. Saying "no results"
    // would tell someone their workspace is empty; say the true thing and give
    // them the way back.
    if (response.status === 401) {
      if (query !== currentSearchQuery) return;
      list.innerHTML =
        '<p class="px-4 py-6 text-center text-sm text-text-muted m-0">' +
        'Your session has expired. <a href="/login" class="font-medium underline">Sign in again</a>' +
        '</p>';
      dropdown.style.display = 'block';
      return;
    }
    if (!response.ok) throw new Error('Search failed');

    const data: SearchResponse = await response.json();
    // A stale response for an older query must not replace fresher results.
    if (query !== currentSearchQuery) return;

    const ranked = data.results ?? [];
    // Keyboard indices address the *rendered* order, so store the regrouped
    // list rather than the raw one.
    activeResults = groupBySection(ranked).flat;
    activeIndex = activeResults.length ? 0 : -1;
    list.innerHTML = renderResults(ranked, query);
    dropdown.style.display = 'block';
    highlightActive(dropdown);
  } catch {
    if (query !== currentSearchQuery) return;
    list.innerHTML = '<p class="px-4 py-6 text-center text-sm text-danger m-0">Search is unavailable right now.</p>';
    dropdown.style.display = 'block';
  }
}

function initializeNavbarSearch(): void {
  const searchInput = document.getElementById('navbar-search-input') as HTMLInputElement | null;
  const dropdown = document.getElementById('search-results-dropdown');
  if (!searchInput || !dropdown) return;

  // The navbar survives HTMX swaps, so re-running this would stack a second
  // set of listeners on the same input — and every arrow key would then move
  // two rows per press. Bind once per element, and re-bind only if a swap
  // actually replaced it.
  if (searchInput.dataset.spotlightBound === 'true') return;
  searchInput.dataset.spotlightBound = 'true';

  searchInput.addEventListener('input', (e) => {
    debounceSearch(() => performSearch((e.target as HTMLInputElement).value.trim()));
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      dropdown.style.display = 'none';
      searchInput.blur();
      return;
    }
    if (!activeResults.length || dropdown.style.display === 'none') return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % activeResults.length;
      highlightActive(dropdown);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + activeResults.length) % activeResults.length;
      highlightActive(dropdown);
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      window.location.href = activeResults[activeIndex].url;
    }
  });

  document.addEventListener('click', (e) => {
    if (!searchInput.contains(e.target as Node) && !dropdown.contains(e.target as Node)) {
      dropdown.style.display = 'none';
    }
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeNavbarSearch);
} else {
  initializeNavbarSearch();
}

document.body.addEventListener('htmx:afterSwap', () => {
  initializeNavbarSearch();
});
