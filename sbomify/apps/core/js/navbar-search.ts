/**
 * Spotlight search for the navbar.
 *
 * Navigation first: the endpoint returns a flat, ranked `results` list where
 * app destinations (settings, tokens, wizards) outrank the workspace's own
 * products and components. This renders that list grouped by section, in the
 * order the server ranked it — the client does no re-sorting, so changing
 * priorities is a server-side concern only.
 *
 * Deliberately plain markup: the palette's visual design is a follow-up, and
 * a thin renderer is easier to replace than a clever one. Arrow keys, Enter
 * and Escape work because a palette nobody can drive from the keyboard is not
 * a palette.
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
  return div.innerHTML;
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
    return `<div class="search-results-empty"><p class="text-muted mb-0">No results for "${escapeHtml(query)}"</p></div>`;
  }

  let html = '<div class="search-results-content">';
  let index = 0;

  for (const section of groupBySection(results).sections) {
    html += `
      <div class="search-results-section">
        <div class="search-results-section-header"><span>${escapeHtml(section[0].section_label)}</span></div>
        <div class="search-results-list">
    `;
    for (const result of section) {
      html += `
        <a href="${escapeHtml(result.url)}" class="search-result-item" data-index="${index}">
          <div class="search-result-item-content">
            <div class="search-result-item-name"><i class="fas ${escapeHtml(result.icon)} me-2"></i>${escapeHtml(result.title)}</div>
          </div>
          <i class="fas fa-chevron-right search-result-item-arrow"></i>
        </a>
      `;
      index += 1;
    }
    html += '</div></div>';
  }

  html += '</div>';
  return html;
}

function highlightActive(dropdown: HTMLElement): void {
  dropdown.querySelectorAll('.search-result-item').forEach((el, i) => {
    el.classList.toggle('is-active', i === activeIndex);
    if (i === activeIndex) el.scrollIntoView({ block: 'nearest' });
  });
}

async function performSearch(query: string): Promise<void> {
  const dropdown = document.getElementById('search-results-dropdown');
  if (!dropdown) return;

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
    if (!response.ok) throw new Error('Search failed');

    const data: SearchResponse = await response.json();
    // A stale response for an older query must not replace fresher results.
    if (query !== currentSearchQuery) return;

    const ranked = data.results ?? [];
    // Keyboard indices address the *rendered* order, so store the regrouped
    // list rather than the raw one.
    activeResults = groupBySection(ranked).flat;
    activeIndex = activeResults.length ? 0 : -1;
    dropdown.innerHTML = renderResults(ranked, query);
    dropdown.style.display = 'block';
    highlightActive(dropdown);
  } catch {
    if (query !== currentSearchQuery) return;
    dropdown.innerHTML =
      '<div class="search-results-empty"><p class="text-danger mb-0">Search is unavailable right now.</p></div>';
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
