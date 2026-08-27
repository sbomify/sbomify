import { defaultBrandColors } from '../../core/js/constants/colors';

/**
 * The brand colour maths, mirrored from sbomify/apps/teams/branding.py so a live
 * preview shows what the server will render. Keep the two in step.
 */

// Luminance where white and black text contrast equally: sqrt(0.0525) - 0.05.
const CONTRAST_PIVOT = Math.sqrt(0.0525) - 0.05;
const HEX = /^#[0-9a-f]{6}$/i;

function relativeLuminance(hex: string): number {
    const [red, green, blue] = [1, 3, 5].map((i) => {
        const srgb = parseInt(hex.slice(i, i + 2), 16) / 255;
        return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The colour a branded surface paints with: the workspace's, or the platform accent. */
export function brandFill(color: string | null | undefined): string {
    return color && HEX.test(color.trim()) ? color.trim() : defaultBrandColors.accent;
}

/** The text colour that belongs on top of a brand colour. */
export function inkOnColor(color: string | null | undefined): string {
    return relativeLuminance(brandFill(color)) < CONTRAST_PIVOT ? '#ffffff' : defaultBrandColors.primary;
}
