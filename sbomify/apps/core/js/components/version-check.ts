/**
 * "Am I affected?" for a version the reader types.
 *
 * The page lists each product's affected ranges, and a reader holding a
 * version wants a yes or no, not a list to scan. This tests the typed version
 * against the same ranges the page shows and says which applies.
 *
 * It only answers when it can. Versions compare segment by segment when both
 * sides are dotted numbers (an optional leading "v", a pre-release after "-",
 * build metadata after "+" ignored). Anything else, a commit hash or a date
 * tag, matches by equality alone, so a pinned commit still answers while a
 * span bounded by one says it cannot tell rather than guessing.
 */

export interface VersionRange {
    label: string;
    introduced: string;
    fixed: string;
    last_affected: string;
}

export interface VersionSubject {
    suppressed: boolean;
    ranges: VersionRange[];
}

export type RangeMatch = 'in' | 'out' | 'unknown';
export type Verdict = 'affected' | 'not_affected' | 'unknown';

interface ParsedVersion {
    core: number[];
    pre: string;
}

const NUMERIC = /^v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/i;

function normalize(value: string): string {
    return value.trim().toLowerCase().replace(/^v(?=\d)/, '');
}

export function parseVersion(value: string): ParsedVersion | null {
    const match = NUMERIC.exec(value.trim());
    if (!match) return null;
    return { core: match[1].split('.').map(Number), pre: match[2] ?? '' };
}

/** -1, 0 or 1, or null when the two cannot be ordered. */
export function compareVersions(a: string, b: string): number | null {
    const left = parseVersion(a);
    const right = parseVersion(b);
    if (!left || !right) {
        return normalize(a) === normalize(b) ? 0 : null;
    }
    const length = Math.max(left.core.length, right.core.length);
    for (let i = 0; i < length; i++) {
        const diff = (left.core[i] ?? 0) - (right.core[i] ?? 0);
        if (diff !== 0) return Math.sign(diff);
    }
    // 1.0.0-rc1 comes before 1.0.0, the same as semver.
    if (left.pre === right.pre) return 0;
    if (!left.pre) return 1;
    if (!right.pre) return -1;
    return left.pre < right.pre ? -1 : 1;
}

export function rangeMatch(range: VersionRange, version: string): RangeMatch {
    const { introduced, fixed, last_affected: last } = range;
    if (introduced && introduced === last) {
        // A pinned version, often a commit: it holds only that one.
        return compareVersions(version, introduced) === 0 ? 'in' : 'out';
    }
    const checks: Array<[string, (order: number) => boolean]> = [];
    if (introduced) checks.push([introduced, (order) => order >= 0]);
    if (fixed) checks.push([fixed, (order) => order < 0]);
    if (last) checks.push([last, (order) => order <= 0]);
    let unknown = false;
    for (const [bound, holds] of checks) {
        const order = compareVersions(version, bound);
        if (order === null) {
            unknown = true;
            continue;
        }
        if (!holds(order)) return 'out';
    }
    return unknown ? 'unknown' : 'in';
}

export function verdictFor(subject: VersionSubject | undefined, version: string): Verdict | null {
    if (!subject || !version.trim()) return null;
    if (subject.suppressed) return 'not_affected';
    if (!subject.ranges.length) return 'unknown';
    const matches = subject.ranges.map((range) => rangeMatch(range, version));
    if (matches.includes('in')) return 'affected';
    if (matches.includes('unknown')) return 'unknown';
    return 'not_affected';
}

const VARIANTS: Record<Verdict, string> = {
    affected: 'danger',
    not_affected: 'success',
    unknown: 'secondary',
};

export function verdictText(verdict: Verdict, version: string): string {
    const shown = version.trim();
    if (verdict === 'affected') return `${shown} is affected`;
    if (verdict === 'not_affected') return `${shown} is not affected`;
    return `Can't check ${shown} automatically`;
}

export function versionCheck(dataId: string) {
    return {
        query: '',
        subjects: {} as Record<string, VersionSubject>,

        init(): void {
            this.subjects = (window.parseJsonScript(dataId) as Record<string, VersionSubject> | null) ?? {};
        },

        verdict(key: string): Verdict | null {
            return verdictFor(this.subjects[key], this.query);
        },

        /** The badge variant for a row's verdict, bound to data-variant. */
        variant(key: string): string | null {
            const verdict = this.verdict(key);
            return verdict ? VARIANTS[verdict] : null;
        },

        text(key: string): string {
            const verdict = this.verdict(key);
            return verdict ? verdictText(verdict, this.query) : '';
        },

        /** Whether one listed range holds the typed version, bound to data-match. */
        match(key: string, index: number): RangeMatch | null {
            const range = this.subjects[key]?.ranges[index];
            if (!range || !this.query.trim()) return null;
            return rangeMatch(range, this.query);
        },

        /** One sentence for a screen reader, since the verdicts are spread over the rows. */
        get summary(): string {
            const version = this.query.trim();
            if (!version) return '';
            const verdicts = Object.keys(this.subjects).map((key) => this.verdict(key));
            const affected = verdicts.filter((verdict) => verdict === 'affected').length;
            if (affected) return `${version} is affected in ${affected} of ${verdicts.length} products.`;
            if (verdicts.includes('unknown')) return `${version} could not be checked for every product.`;
            return `${version} is not affected.`;
        },
    };
}
