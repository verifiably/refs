/** A refs refusal: `kind` names the error class, `detail` says why, `position` locates it.
 *
 * `position` is a 0-based code-point index into the offending text, and is absent when the
 * refusal has no single location. */
export class RefsError extends Error {
  readonly kind: string;
  readonly detail: string;
  readonly position: number | undefined;

  constructor(kind: string, detail: string, position?: number) {
    super(`${kind}: ${detail}${position === undefined ? "" : ` (at ${position})`}`);
    this.name = "RefsError";
    this.kind = kind;
    this.detail = detail;
    this.position = position;
  }
}
