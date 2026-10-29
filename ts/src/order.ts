/** Compare two strings by Unicode code point: the ordering Python's `<` on `str` gives.
 *
 * JavaScript's `<` and `localeCompare` order by UTF-16 code unit, which puts an astral
 * character (a surrogate pair starting 0xD800) before the BMP characters 0xE000 to 0xFFFF. */
export function compareCodePoints(a: string, b: string): number {
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    const x = a.codePointAt(i) as number;
    const y = b.codePointAt(j) as number;
    if (x !== y) return x < y ? -1 : 1;
    i += x > 0xffff ? 2 : 1;
    j += y > 0xffff ? 2 : 1;
  }
  if (i < a.length) return 1;
  if (j < b.length) return -1;
  return 0;
}
