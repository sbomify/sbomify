import { copyToClipboard } from '../clipboard';

/** Sharing is available to readers of the action, independently of visibility administration. */
export function publicSharing(publicUrl: string) {
    const absoluteUrl = () => new URL(publicUrl, window.location.origin).href;
    return {
        copyToClipboard() {
            return copyToClipboard(absoluteUrl(), 'Public URL copied to clipboard', 'Failed to copy URL to clipboard');
        },
        copyBadgeToClipboard() {
            const badge = `[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](${absoluteUrl()})`;
            return copyToClipboard(badge, 'Badge markdown copied to clipboard', 'Failed to copy badge to clipboard');
        },
    };
}
