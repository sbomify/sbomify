export const EU_COUNTRIES = [
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
  'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
  'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
];

const regionNames = new Intl.DisplayNames(['en'], { type: 'region' });

export const EU_COUNTRY_NAMES: Record<string, string> = Object.fromEntries(
  EU_COUNTRIES.map(code => [code, regionNames.of(code) ?? code]),
);
