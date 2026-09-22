import type { AlpineComponent } from 'alpinejs';

interface SpotlightResult {
  title: string;
  url: string;
  section: string;
  section_label: string;
  icon: string;
  query?: string;
}

interface SearchOption extends SpotlightResult {
  index: number;
}

interface SearchSection {
  key: string;
  label: string;
  results: SearchOption[];
}

interface NavbarSearch {
  query: string;
  open: boolean;
  status: 'suggested' | 'idle' | 'loading' | 'ready' | 'error' | 'expired';
  sections: SearchSection[];
  suggestions: SpotlightResult[];
  activeIndex: number;
  readonly results: SearchOption[];
  readonly activeId: string | null;
  readonly announcement: string;
  shortcutLabel: string;
  timer: ReturnType<typeof setTimeout> | undefined;
  request: AbortController | undefined;
  revision: number;
  update(value: string, composing?: boolean): void;
  setResults(results: SpotlightResult[]): void;
  showSuggestions(): void;
  choose(event: MouseEvent, result: SpotlightResult): void;
  show(): void;
  cancel(): void;
  dismiss(): void;
  search(): Promise<void>;
  keydown(event: KeyboardEvent): void;
  shortcut(event: KeyboardEvent): void;
  reveal(): void;
}

/** The component owns markup. Alpine owns selection and the existing search request. */
export function navbarSearch(): AlpineComponent<NavbarSearch> {
  return {
    query: '',
    open: false,
    status: 'idle',
    sections: [],
    suggestions: [],
    activeIndex: -1,
    shortcutLabel: /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl',
    timer: undefined,
    request: undefined,
    revision: 0,

    init() {
      this.suggestions = window.parseJsonScript(`${this.$root.id}-suggestions`) ?? [];
    },

    get results() {
      return this.sections.flatMap(section => section.results);
    },
    get activeId() {
      return this.open && this.activeIndex >= 0 ? `${this.$root.id}-option-${this.activeIndex}` : null;
    },
    get announcement() {
      if (!this.open) return '';
      if (this.status === 'suggested') return `${this.results.length} suggestions. Choose a page or try a search.`;
      if (this.status === 'loading') return 'Searching...';
      if (this.status === 'error') return 'Search is unavailable right now.';
      if (this.status === 'expired') return 'Your session has expired. Sign in again.';
      return `${this.results.length} ${this.results.length === 1 ? 'result' : 'results'}.`;
    },

    update(value, composing = false) {
      this.cancel();
      this.query = value.trim();
      this.open = true;
      if (this.query.length < 2 || composing) {
        this.showSuggestions();
        return;
      }
      this.sections = [];
      this.activeIndex = -1;
      this.status = 'loading';
      this.timer = setTimeout(() => void this.search(), 200);
    },

    setResults(results) {
      // Preserve server ranking within each section, and index the displayed order.
      const groups = new Map<string, SearchSection>();
      for (const result of results) {
        if (!groups.has(result.section)) {
          groups.set(result.section, { key: result.section, label: result.section_label, results: [] });
        }
        groups.get(result.section)!.results.push({ ...result, index: 0 });
      }
      this.sections = [...groups.values()];
      this.results.forEach((result, index) => { result.index = index; });
      this.activeIndex = this.results.length ? 0 : -1;
      this.$refs.list.scrollTop = 0;
    },

    showSuggestions() {
      this.status = 'suggested';
      this.setResults(this.suggestions);
    },

    show() {
      if (this.open) return;
      this.open = true;
      if (this.query.length < 2) this.showSuggestions();
      else if (this.status === 'idle') void this.search();
      else this.$nextTick(() => this.reveal());
    },

    choose(event, result) {
      if (!result.query || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        this.dismiss();
        return;
      }
      event.preventDefault();
      const input = this.$refs.input as HTMLInputElement;
      input.value = result.query;
      input.focus({ preventScroll: true });
      this.update(result.query);
      void this.search();
    },

    cancel() {
      clearTimeout(this.timer);
      this.request?.abort();
      this.revision += 1;
    },

    dismiss() {
      this.cancel();
      this.open = false;
      if (this.status === 'loading') this.status = 'idle';
    },

    async search() {
      this.cancel();
      const revision = this.revision;
      this.request = new AbortController();
      this.status = 'loading';
      this.activeIndex = -1;
      this.sections = [];
      try {
        const url = new URL(this.$root.dataset.searchUrl!, window.location.origin);
        url.search = new URLSearchParams({ q: this.query, limit: '10' }).toString();
        const response = await fetch(url, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          signal: this.request.signal,
        });
        if (revision !== this.revision) return;
        if (response.status === 401) {
          this.status = 'expired';
          return;
        }
        if (!response.ok) throw new Error('Search failed');
        const data: { results?: SpotlightResult[] } = await response.json();
        if (revision !== this.revision) return;

        this.setResults(data.results ?? []);
        this.status = 'ready';
      } catch {
        if (revision === this.revision) this.status = 'error';
      }
    },

    keydown(event) {
      if (event.isComposing || event.keyCode === 229 || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === 'Escape' && this.open) {
        event.preventDefault();
        event.stopPropagation();
        this.$refs.input.focus({ preventScroll: true });
        this.dismiss();
        return;
      }
      if (event.target !== this.$refs.input) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const wasOpen = this.open;
        this.show();
        if (!this.results.length) return;
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        this.activeIndex = wasOpen
          ? (this.activeIndex + direction + this.results.length) % this.results.length
          : direction === 1 ? 0 : this.results.length - 1;
        this.$nextTick(() => this.reveal());
      } else if (event.key === 'Enter' && this.activeId) {
        event.preventDefault();
        this.$root.querySelector<HTMLAnchorElement>(`#${this.activeId}`)?.click();
      }
    },

    shortcut(event) {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k' || event.isComposing) return;
      event.preventDefault();
      const input = this.$refs.input as HTMLInputElement;
      input.focus({ preventScroll: true });
      input.select();
      this.show();
    },

    reveal() {
      const list = this.$refs.list;
      if (this.activeIndex === 0) {
        list.scrollTop = 0;
        return;
      }
      const option = list.querySelector('[aria-selected="true"]');
      if (!option) return;
      const bounds = list.getBoundingClientRect();
      const row = option.getBoundingClientRect();
      // Scroll only the result list. scrollIntoView also moves the page behind it.
      if (row.top < bounds.top + 8) list.scrollTop += row.top - bounds.top - 8;
      else if (row.bottom > bounds.bottom - 8) list.scrollTop += row.bottom - bounds.bottom + 8;
    },

    destroy() {
      this.cancel();
    },
  };
}
