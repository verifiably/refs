/** The pattern dialect: the grammar every stored identifier pattern is in (spec section 5.2).
 *
 * The grammar is the authority, not either regex engine. `checkPattern` parses a pattern
 * against it and throws `unsupported_pattern` at the 0-based code-point index of the first
 * character the grammar cannot accept (the length of the pattern when it ends too soon).
 * `compilePattern` compiles only a pattern the grammar accepted. The grammar and every
 * position are those of the Python package; `fixtures/dialect.syntax.json` pins both.
 *
 *     pattern     = alternation
 *     alternation = sequence { "|" sequence }
 *     sequence    = { item }
 *     item        = "^" (index 0 only) | "$" (last character only) | atom [ quantifier ]
 *     atom        = literal | escape | class | group
 *     group       = "(" alternation ")" | "(?:" alternation ")"
 *     quantifier  = ( "?" | "*" | "+" | "{" m "}" | "{" m "," "}" | "{" m "," n "}" ) [ "?" ]
 *     class       = "[" [ "^" ] member-or-range { member-or-range } "]"
 *
 * The empty pattern, empty branches and empty groups are accepted. Digits in a quantifier
 * are ASCII digits, at most five of them (leading zeros count), each bound at most 65535,
 * and m must not exceed n. Groups nest at most 32 deep. Inside a class, the doubled
 * unescaped characters `&&`, `~~` and `||` are refused: Python reserves them for set
 * operations.
 */

import { RefsError } from "./errors.js";

const SYNTAX = new Set(Array.from("\\^$.|?*+()[]{}"));
const CONTROL = new Map([
  ["t", "\t"],
  ["n", "\n"],
  ["v", "\v"],
  ["f", "\f"],
  ["r", "\r"],
]);
const OUTSIDE_ESCAPES = new Set([...SYNTAX, "/"]);
const CLASS_ESCAPES = new Set(Array.from("\\][^-"));
const CLASS_PLAIN_EXCLUDED = new Set(Array.from("\\][^-"));
const CLASS_RESERVED_DOUBLES = new Set(Array.from("&~|"));
const DIGITS = new Set(Array.from("0123456789"));
const QUANTIFIERS = new Set(Array.from("?*+{"));
const MAX_COUNT = 65535; // largest quantifier bound; above it the engines differ or Python refuses
const MAX_DIGITS = String(MAX_COUNT).length; // a longer digit run is refused before any conversion
const MAX_DEPTH = 32; // deepest group nesting

function refuse(detail: string, position: number): RefsError {
  return new RefsError("unsupported_pattern", detail, position);
}

function show(c: string): string {
  return `'${c}'`;
}

/** Code-point order of two single code points (a string compare would use UTF-16 units). */
function reversed(lo: string, hi: string): boolean {
  return (lo.codePointAt(0) as number) > (hi.codePointAt(0) as number);
}

class Parser {
  private readonly chars: string[];
  private readonly n: number;
  private i = 0;

  constructor(pattern: string) {
    this.chars = Array.from(pattern); // positions count code points, not UTF-16 units
    this.n = this.chars.length;
  }

  private peek(): string | null {
    return this.i < this.n ? this.chars[this.i] : null;
  }

  parse(): void {
    this.alternation(0);
    if (this.i < this.n) throw refuse("unmatched )", this.i); // only an unmatched ")" stops the top level early
  }

  private alternation(depth: number): void {
    this.sequence(depth);
    while (this.peek() === "|") {
      this.i += 1;
      this.sequence(depth);
    }
  }

  private sequence(depth: number): void {
    for (;;) {
      const c = this.peek();
      if (c === null || c === "|" || (c === ")" && depth > 0)) return;
      if (c === ")") throw refuse("unmatched )", this.i);
      if (c === "^") {
        if (this.i !== 0) throw refuse("^ is allowed only at the start of the pattern", this.i);
        this.i += 1;
      } else if (c === "$") {
        if (this.i !== this.n - 1) throw refuse("$ is allowed only at the end of the pattern", this.i);
        this.i += 1;
      } else {
        this.atom(depth);
        this.quantified();
      }
    }
  }

  private atom(depth: number): void {
    const c = this.chars[this.i];
    if (QUANTIFIERS.has(c)) throw refuse(`nothing to quantify before ${show(c)}`, this.i);
    if (c === "\\") {
      this.escape(false);
    } else if (c === "[") {
      this.charClass();
    } else if (c === "(") {
      this.group(depth);
    } else if (SYNTAX.has(c)) {
      throw refuse(`unescaped ${show(c)} is outside the dialect`, this.i);
    } else {
      this.i += 1;
    }
  }

  /** Consume a backslash escape; return the code point it denotes. */
  private escape(inClass: boolean): string {
    const start = this.i;
    if (start + 1 >= this.n) throw refuse("trailing backslash", start);
    const c = this.chars[start + 1];
    const control = CONTROL.get(c);
    if (control !== undefined) {
      this.i += 2;
      return control;
    }
    if ((inClass ? CLASS_ESCAPES : OUTSIDE_ESCAPES).has(c)) {
      this.i += 2;
      return c;
    }
    throw refuse(`escape \\${c} is outside the dialect`, start);
  }

  private group(depth: number): void {
    if (depth >= MAX_DEPTH) throw refuse(`groups nest at most ${MAX_DEPTH} deep`, this.i);
    this.i += 1; // (
    if (this.peek() === "?") {
      if (this.chars[this.i + 1] !== ":") throw refuse("only (?: is allowed after (", this.i);
      this.i += 2;
    }
    this.alternation(depth + 1);
    if (this.peek() !== ")") throw refuse("unclosed group", this.i);
    this.i += 1;
  }

  private charClass(): void {
    this.i += 1; // [
    if (this.peek() === "^") this.i += 1;
    let members = 0;
    for (;;) {
      const c = this.peek();
      if (c === null) throw refuse("unclosed class", this.i);
      if (c === "]") {
        if (members === 0) throw refuse("a class holds at least one member", this.i);
        this.i += 1;
        return;
      }
      const firstAt = this.i;
      const lo = this.member();
      if (this.peek() === "-") {
        const dashAt = this.i;
        this.i += 1;
        if (this.peek() === "]") throw refuse("- must sit between two members", dashAt);
        const hi = this.member();
        if (reversed(lo, hi)) throw refuse("range is reversed", firstAt);
      }
      members += 1;
    }
  }

  private member(): string {
    const c = this.peek();
    if (c === null) throw refuse("unclosed class", this.i);
    if (c === "\\") return this.escape(true);
    if (CLASS_PLAIN_EXCLUDED.has(c)) throw refuse(`unescaped ${show(c)} is not a class member here`, this.i);
    if (CLASS_RESERVED_DOUBLES.has(c) && this.i > 0 && this.chars[this.i - 1] === c) {
      throw refuse(`doubled ${show(c)} in a class is reserved for set operations`, this.i);
    }
    this.i += 1;
    return c;
  }

  private quantified(): void {
    const c = this.peek();
    if (c === null || !QUANTIFIERS.has(c)) return;
    if (c === "{") this.braces();
    else this.i += 1;
    if (this.peek() === "?") this.i += 1; // lazy
  }

  private braces(): void {
    const start = this.i;
    this.i += 1; // {
    const lo = this.digits(start);
    let hi: number | null = lo;
    if (this.peek() === ",") {
      this.i += 1;
      const next = this.peek();
      hi = next !== null && DIGITS.has(next) ? this.digits(start) : null;
    }
    if (this.peek() !== "}") throw refuse("malformed quantifier", start);
    this.i += 1;
    if (hi !== null && lo > hi) throw refuse("quantifier lower bound exceeds upper bound", start);
  }

  private digits(start: number): number {
    const from = this.i;
    while (this.i < this.n && DIGITS.has(this.chars[this.i])) this.i += 1;
    if (from === this.i) throw refuse("malformed quantifier", start);
    if (this.i - from > MAX_DIGITS) throw refuse(`quantifier bound has more than ${MAX_DIGITS} digits`, start);
    const value = Number(this.chars.slice(from, this.i).join(""));
    if (value > MAX_COUNT) throw refuse(`quantifier bound exceeds ${MAX_COUNT}`, start);
    return value;
  }
}

/** Refuse a pattern outside the dialect with `unsupported_pattern` and a code-point position. */
export function checkPattern(pattern: string): void {
  new Parser(pattern).parse();
}

/** Check `pattern`, then compile it for a full match of a whole identifier, `u` flag on.
 * An engine error after a clean check is `invalid_pattern`. */
export function compilePattern(pattern: string): RegExp {
  checkPattern(pattern);
  try {
    return new RegExp(`^(?:${pattern})$`, "u");
  } catch (error) {
    throw new RefsError("invalid_pattern", `engine refused a pattern the grammar accepted: ${String(error)}`);
  }
}
