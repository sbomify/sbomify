import { getCsrfToken } from '../../core/js/csrf';

/** The existing OSCAL import API accepts a file's JSON body or JSON read from a URL. */
export function catalogImport(importUrl: string) {
    return {
        open: false,
        importing: false,
        error: '',
        mode: 'file',
        url: '',
        async importCatalog(file?: File) {
            if (this.importing) return;
            this.error = '';
            this.importing = true;
            try {
                let body: string;
                if (this.mode === 'file') {
                    if (!file) throw new Error('Choose an OSCAL JSON file.');
                    body = await file.text();
                } else {
                    const source = new URL(this.url);
                    if (!['http:', 'https:'].includes(source.protocol)) throw new Error('Enter an HTTP or HTTPS URL.');
                    const response = await fetch(source);
                    if (!response.ok) throw new Error('Could not read the catalog URL.');
                    body = await response.text();
                }
                const response = await fetch(importUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                    body,
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Could not import the catalog.');
                window.location.reload();
            } catch (error) {
                this.error = error instanceof Error ? error.message : 'Could not import the catalog.';
            } finally {
                this.importing = false;
            }
        },
    };
}
