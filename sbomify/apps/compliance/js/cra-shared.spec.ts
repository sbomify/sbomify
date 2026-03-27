import { describe, test, expect } from 'bun:test';

// Test the EU countries shared module since it's pure data
import { EU_COUNTRIES, EU_COUNTRY_NAMES } from './eu-countries';

describe('EU Countries', () => {
  test('has 27 EU member states', () => {
    expect(EU_COUNTRIES).toHaveLength(27);
  });

  test('all country codes are 2-letter uppercase', () => {
    for (const code of EU_COUNTRIES) {
      expect(code).toMatch(/^[A-Z]{2}$/);
    }
  });

  test('every country code has a name', () => {
    for (const code of EU_COUNTRIES) {
      expect(EU_COUNTRY_NAMES[code]).toBeDefined();
      expect(EU_COUNTRY_NAMES[code].length).toBeGreaterThan(0);
    }
  });

  test('includes key EU members', () => {
    expect(EU_COUNTRIES).toContain('DE');
    expect(EU_COUNTRIES).toContain('FR');
    expect(EU_COUNTRIES).toContain('IT');
    expect(EU_COUNTRIES).toContain('ES');
    expect(EU_COUNTRIES).toContain('PL');
  });

  test('country names are correct', () => {
    expect(EU_COUNTRY_NAMES['DE']).toBe('Germany');
    expect(EU_COUNTRY_NAMES['FR']).toBe('France');
    expect(EU_COUNTRY_NAMES['IT']).toBe('Italy');
  });

  test('does not include non-EU countries', () => {
    expect(EU_COUNTRIES).not.toContain('GB'); // UK left EU
    expect(EU_COUNTRIES).not.toContain('CH'); // Switzerland
    expect(EU_COUNTRIES).not.toContain('NO'); // Norway
    expect(EU_COUNTRIES).not.toContain('US');
  });
});
