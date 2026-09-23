import { getCsrfToken } from '../csrf';

interface SetupConfig {
    baseUrl: string;
    instructionsUrl: string;
    tokenUrl: string;
}

interface SetupCredential {
    id: number;
    token: string;
    expires_at: string;
}

const shellQuote = (value: string): string => `'${value.replace(/'/g, "'\"'\"'")}'`;

export function repositorySetup(config: Partial<SetupConfig> = {}) {
    const baseUrl = config.baseUrl || 'https://app.sbomify.com';
    const dockerUrl = new URL(baseUrl);
    if (['localhost', '127.0.0.1', '[::1]'].includes(dockerUrl.hostname)) {
        dockerUrl.hostname = 'host.docker.internal';
    }
    return {
        method: 'agent',
        runtime: 'docker',
        visibility: 'private',
        token: '',
        tokenId: null as number | null,
        expiresAt: '',
        minting: false,
        error: '',

        get agentPrompt(): string {
            return `Set up sbomify for this repository.\n\nRead ${config.instructionsUrl || `${baseUrl}/setup.md`} and follow it exactly.\n\nAPI     ${baseUrl}/api/v1\nAuth    Authorization: Bearer ${this.token || 'YOUR_SETUP_TOKEN'}\nCreate everything as ${this.visibility}.\n\nReview the proposed changes with me before applying them.`;
        },

        get command(): string {
            const credential = this.token || 'YOUR_SETUP_TOKEN';
            if (this.runtime === 'uv') {
                return `SBOMIFY_TOKEN=${shellQuote(credential)} uvx sbomify-action wizard --api-base-url ${shellQuote(baseUrl)}`;
            }
            return [
                'docker run --rm -it \\',
                '  -v "$(pwd):/workspace" \\',
                `  -e SBOMIFY_TOKEN=${shellQuote(credential)} \\`,
                '  ghcr.io/sbomify/sbomify-action \\',
                `  sbomify-action wizard --api-base-url ${shellQuote(dockerUrl.toString().replace(/\/$/, ''))}`,
            ].join('\n');
        },

        async mint(): Promise<void> {
            if (this.minting || !config.tokenUrl) return;
            this.minting = true;
            this.error = '';
            const body = new URLSearchParams();
            if (this.tokenId !== null) body.set('previous_id', String(this.tokenId));
            try {
                const response = await fetch(config.tokenUrl, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCsrfToken() },
                    body,
                });
                if (!response.ok) throw new Error('Setup token unavailable');
                const data = await response.json() as SetupCredential;
                this.token = data.token;
                this.tokenId = data.id;
                this.expiresAt = new Date(data.expires_at).toLocaleDateString(undefined, {
                    year: 'numeric', month: 'short', day: 'numeric',
                });
            } catch {
                this.error = 'Could not create a setup token. Try again or open API tokens in Settings.';
            } finally {
                this.minting = false;
            }
        },
    };
}
