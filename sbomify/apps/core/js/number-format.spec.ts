import { describe, expect, test } from 'bun:test';
import { formatNumber } from './number-format';

describe('display number formatting', () => {
  test.each([
    [0, '0'], [999, '999'], [1000, '1,000'], [12345678, '12,345,678'],
    [-12345, '-12,345'], [1234.56789, '1,234.56789'],
    ['1234.00', '1,234.00'], ['1,234', '1,234'], ['96%', '96%'],
    ['—', '—'], ['', ''], [null, ''], [undefined, ''],
  ])('formats %p as %p', (value, expected) => {
    expect(formatNumber(value)).toBe(expected);
  });
});
