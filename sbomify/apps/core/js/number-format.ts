/** Match Django's English intcomma display without changing numeric state. */
export function formatNumber(value: number | string | null | undefined): string {
  if (value == null) return '';
  // Group the integer portion without rounding decimals or coercing placeholders.
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
  const [integer, fraction] = text.split('.');
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}
