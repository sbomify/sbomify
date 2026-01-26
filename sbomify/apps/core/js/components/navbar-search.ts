import Alpine from 'alpinejs';

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

interface NavbarSearchData {
    query: string;
    results: SearchResponse | null;
    loading: boolean;
    showDropdown: boolean;
    searchTimeout: ReturnType<typeof setTimeout> | null;
    lastQuery: string;
    $el: HTMLElement;
    init: () => void;
    handleClickAway: () => void;
    performSearch: () => Promise<void>;
    debounceSearch: () => void;
    handleKeydown: (event: KeyboardEvent) => void;
    handleFocus: () => void;
    handleBlur: () => void;
    getItemUrl: (type: string, id: string) => string;
    formatDescription: (description: string | undefined, maxLength?: number) => string;
    destroy: () => void;
}

const SEARCH_DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 2;

function getSearchUrl(query: string): string {
    const params = new URLSearchParams({ q: query, limit: '10' });
    return `/search/?${params.toString()}`;
}

export function registerNavbarSearch(): void {
    Alpine.data('navbarSearch', (): NavbarSearchData => {
        return {
            query: '',
            results: null,
            loading: false,
            showDropdown: false,
            searchTimeout: null,
            lastQuery: '',
            $el: {} as HTMLElement, // Will be set by Alpine

            init(this: NavbarSearchData) {
                // Click-outside handling is now done via @click.away in template
            },
            
            handleClickAway(this: NavbarSearchData) {
                // Close dropdown when clicking outside
                this.showDropdown = false;
            },

            async performSearch(this: NavbarSearchData): Promise<void> {
                const trimmedQuery = this.query.trim();
                
                if (trimmedQuery.length < MIN_QUERY_LENGTH) {
                    this.showDropdown = false;
                    this.results = null;
                    this.lastQuery = '';
                    return;
                }

                this.loading = true;
                this.showDropdown = true;

                try {
                    const response = await fetch(getSearchUrl(trimmedQuery), {
                        method: 'GET',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                    });

                    if (!response.ok) {
                        throw new Error('Search failed');
                    }

                    const data: SearchResponse = await response.json();

                    // Only update if this is still the current query
                    if (trimmedQuery === this.query.trim()) {
                        this.lastQuery = trimmedQuery;
                        this.results = data;
                        this.loading = false;
                    }
                } catch {
                    if (trimmedQuery === this.query.trim()) {
                        this.results = null;
                        this.loading = false;
                    }
                }
            },

            debounceSearch(this: NavbarSearchData): void {
                if (this.searchTimeout) {
                    clearTimeout(this.searchTimeout);
                }
                this.searchTimeout = setTimeout(() => {
                    this.performSearch();
                }, SEARCH_DEBOUNCE_MS);
            },

            handleKeydown(this: NavbarSearchData, event: KeyboardEvent): void {
                if (event.key === 'Escape') {
                    this.showDropdown = false;
                    (event.target as HTMLElement).blur();
                }
            },

            handleFocus(this: NavbarSearchData): void {
                // Restore results if query matches
                const trimmedQuery = this.query.trim();
                if (trimmedQuery.length >= MIN_QUERY_LENGTH && trimmedQuery === this.lastQuery && this.results) {
                    this.showDropdown = true;
                }
            },

            handleBlur(this: NavbarSearchData): void {
                // Clear stored results if query is too short
                const trimmedQuery = this.query.trim();
                if (trimmedQuery.length < MIN_QUERY_LENGTH) {
                    this.lastQuery = '';
                    this.results = null;
                }
            },

            getItemUrl(this: NavbarSearchData, type: string, id: string): string {
                const baseUrl = type === 'product' ? '/product/' : type === 'project' ? '/project/' : '/component/';
                return `${baseUrl}${id}/`;
            },

            formatDescription(this: NavbarSearchData, description: string | undefined, maxLength: number = 60): string {
                if (!description) return '';
                if (description.length <= maxLength) return description;
                return description.substring(0, maxLength) + '...';
            },

            destroy(this: NavbarSearchData): void {
                if (this.searchTimeout) {
                    clearTimeout(this.searchTimeout);
                    this.searchTimeout = null;
                }
            }
        };
    });
}
