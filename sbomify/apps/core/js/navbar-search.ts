/**
 * Navbar search functionality
 * Handles search input and displays results for products, projects, and components
 */

interface SearchResult {
  id: string;
  name: string;
  description?: string;
  is_public?: boolean;
  component_type?: string;
}

interface SearchResponse {
  products: SearchResult[];
  projects: SearchResult[];
  components: SearchResult[];
}

let searchTimeout: ReturnType<typeof setTimeout> | null = null;
let currentSearchQuery = '';
let lastSearchQuery = '';
let lastSearchResults: SearchResponse | null = null;

function debounceSearch(callback: () => void, delay: number = 300): void {
  if (searchTimeout) {
    clearTimeout(searchTimeout);
  }
  searchTimeout = setTimeout(callback, delay);
}

function getSearchUrl(query: string): string {
  const params = new URLSearchParams({ q: query, limit: '10' });
  return `/search/?${params.toString()}`;
}

function getItemUrl(type: string, id: string): string {
  const baseUrl = type === 'product' ? '/product/' : type === 'project' ? '/project/' : '/component/';
  return `${baseUrl}${id}/`;
}

function formatDescription(description: string | undefined, maxLength: number = 60): string {
  if (!description) return '';
  if (description.length <= maxLength) return description;
  return description.substring(0, maxLength) + '...';
}

function renderSearchResults(data: SearchResponse, query: string): string {
  if (!data.products.length && !data.projects.length && !data.components.length) {
    return `
      <div class="search-results-empty">
        <p class="text-muted mb-0">No results found for "${escapeHtml(query)}"</p>
      </div>
    `;
  }

  let html = '<div class="search-results-content">';

  // Products section
  if (data.products.length > 0) {
    html += `
      <div class="search-results-section">
        <div class="search-results-section-header">
          <i class="fas fa-cube me-2"></i>
          <span>Products</span>
          <span class="search-results-count">${data.products.length}</span>
        </div>
        <div class="search-results-list">
    `;
    data.products.forEach((item) => {
      html += `
        <a href="${getItemUrl('product', item.id)}" class="search-result-item">
          <div class="search-result-item-content">
            <div class="search-result-item-name">${escapeHtml(item.name)}</div>
            ${item.description ? `<div class="search-result-item-description">${escapeHtml(formatDescription(item.description))}</div>` : ''}
          </div>
          <i class="fas fa-chevron-right search-result-item-arrow"></i>
        </a>
      `;
    });
    html += '</div></div>';
  }

  // Projects section
  if (data.projects.length > 0) {
    html += `
      <div class="search-results-section">
        <div class="search-results-section-header">
          <i class="fas fa-folder me-2"></i>
          <span>Projects</span>
          <span class="search-results-count">${data.projects.length}</span>
        </div>
        <div class="search-results-list">
    `;
    data.projects.forEach((item) => {
      html += `
        <a href="${getItemUrl('project', item.id)}" class="search-result-item">
          <div class="search-result-item-content">
            <div class="search-result-item-name">${escapeHtml(item.name)}</div>
            ${item.description ? `<div class="search-result-item-description">${escapeHtml(formatDescription(item.description))}</div>` : ''}
          </div>
          <i class="fas fa-chevron-right search-result-item-arrow"></i>
        </a>
      `;
    });
    html += '</div></div>';
  }

  // Components section
  if (data.components.length > 0) {
    html += `
      <div class="search-results-section">
        <div class="search-results-section-header">
          <i class="fas fa-puzzle-piece me-2"></i>
          <span>Components</span>
          <span class="search-results-count">${data.components.length}</span>
        </div>
        <div class="search-results-list">
    `;
    data.components.forEach((item) => {
      html += `
        <a href="${getItemUrl('component', item.id)}" class="search-result-item">
          <div class="search-result-item-content">
            <div class="search-result-item-name">${escapeHtml(item.name)}</div>
            ${item.description ? `<div class="search-result-item-description">${escapeHtml(formatDescription(item.description))}</div>` : ''}
          </div>
          <i class="fas fa-chevron-right search-result-item-arrow"></i>
        </a>
      `;
    });
    html += '</div></div>';
  }

  html += '</div>';
  return html;
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function performSearch(query: string): Promise<void> {
  const dropdown = document.getElementById('search-results-dropdown');
  if (!dropdown) return;

  if (query.length < 2) {
    dropdown.style.display = 'none';
    return;
  }

  currentSearchQuery = query;

  try {
    const response = await fetch(getSearchUrl(query), {
      method: 'GET',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
      },
    });

    if (!response.ok) {
      throw new Error('Search failed');
    }

    const data: SearchResponse = await response.json();

    // Only update if this is still the current query (user hasn't typed more)
    if (query === currentSearchQuery) {
      lastSearchQuery = query;
      lastSearchResults = data;
      dropdown.innerHTML = renderSearchResults(data, query);
      dropdown.style.display = 'block';
    }
  } catch {
    if (query === currentSearchQuery) {
      dropdown.innerHTML = `
        <div class="search-results-empty">
          <p class="text-danger mb-0">Error performing search. Please try again.</p>
        </div>
      `;
      dropdown.style.display = 'block';
    }
  }
}

function initializeNavbarSearch(): void {
  const searchInput = document.getElementById('navbar-search-input') as HTMLInputElement;
  const dropdown = document.getElementById('search-results-dropdown');

  if (!searchInput || !dropdown) return;

  // Handle input
  searchInput.addEventListener('input', (e) => {
    const query = (e.target as HTMLInputElement).value.trim();
    if (query.length < 2) {
      // Clear stored results if query is too short
      lastSearchQuery = '';
      lastSearchResults = null;
    }
    debounceSearch(() => performSearch(query));
  });

  // Store search query and results when input loses focus
  searchInput.addEventListener('blur', () => {
    const query = searchInput.value.trim();
    if (query.length < 2) {
      // Clear stored results if query is too short
      lastSearchQuery = '';
      lastSearchResults = null;
    }
  });

  // Restore results when input regains focus if query matches
  searchInput.addEventListener('focus', () => {
    const query = searchInput.value.trim();
    if (query.length >= 2 && query === lastSearchQuery && lastSearchResults) {
      dropdown.innerHTML = renderSearchResults(lastSearchResults, query);
      dropdown.style.display = 'block';
    }
  });

  // Hide dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (dropdown && !searchInput.contains(e.target as Node) && !dropdown.contains(e.target as Node)) {
      dropdown.style.display = 'none';
    }
  });

  // Handle keyboard navigation
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      dropdown.style.display = 'none';
      searchInput.blur();
    }
  });
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeNavbarSearch);
} else {
  initializeNavbarSearch();
}

// Re-initialize after HTMX swaps
document.body.addEventListener('htmx:afterSwap', () => {
  initializeNavbarSearch();
});

