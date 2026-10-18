/**
 * The one error type every adapter throws, so pages handle failures the same way whether the
 * data came from fixtures or the Python API.
 *
 * - `unavailable`: network down, API not running, 5xx. Worth a retry.
 * - `invalid_request`: the API rejected the question (unknown metric, bad range).
 * - `unsupported`: a valid question this data source can't answer yet.
 * - `unknown`: anything else.
 */
export type BaseballApiErrorKind = "unavailable" | "invalid_request" | "unsupported" | "unknown";

export class BaseballApiError extends Error {
  readonly kind: BaseballApiErrorKind;
  /** Seconds the service asked us to wait before retrying (its Retry-After header), if any. */
  readonly retryAfterSeconds: number | null;

  constructor(kind: BaseballApiErrorKind, message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "BaseballApiError";
    this.kind = kind;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function toBaseballApiError(error: unknown): BaseballApiError {
  if (error instanceof BaseballApiError) return error;
  if (error instanceof Error) return new BaseballApiError("unknown", error.message);
  return new BaseballApiError("unknown", String(error));
}
