import { describe, it, expect } from 'bun:test';

// Extract and test the formatDate logic independently
// since the full component requires Alpine.js and DOM
function formatDate(dateString: string, now: Date = new Date()): string {
    const date = new Date(dateString);
    const isToday =
        date.getDate() === now.getDate() &&
        date.getMonth() === now.getMonth() &&
        date.getFullYear() === now.getFullYear();

    if (isToday) return 'Today';

    const diffInMs = now.getTime() - date.getTime();
    const diffInDays = Math.round(diffInMs / (1000 * 60 * 60 * 24));

    if (diffInDays > 7) {
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    }

    const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
    return rtf.format(-diffInDays, 'day');
}

describe('access-tokens-list formatDate', () => {
    const fixedNow = new Date('2026-01-03T12:00:00Z');

    it('returns "Today" for current date', () => {
        const todayDate = '2026-01-03T09:30:00Z';
        expect(formatDate(todayDate, fixedNow)).toBe('Today');
    });

    it('returns "yesterday" for one day ago', () => {
        const yesterdayDate = '2026-01-02T12:00:00Z';
        expect(formatDate(yesterdayDate, fixedNow)).toBe('yesterday');
    });

    it('returns relative time for dates within 7 days', () => {
        const threeDaysAgo = '2025-12-31T12:00:00Z';
        expect(formatDate(threeDaysAgo, fixedNow)).toBe('3 days ago');
    });

    it('returns formatted date for dates older than 7 days', () => {
        const oldDate = '2025-12-20T12:00:00Z';
        expect(formatDate(oldDate, fixedNow)).toBe('Dec 20, 2025');
    });

    it('returns formatted date for much older dates', () => {
        const veryOldDate = '2024-06-15T12:00:00Z';
        expect(formatDate(veryOldDate, fixedNow)).toBe('Jun 15, 2024');
    });
});
