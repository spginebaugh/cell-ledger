import { client } from "@/api/generated/client.gen";

/** The API's own error body, surfaced with its `detail`. */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

client.setConfig({ baseUrl: "" });

type Result<T> = { data?: T; error?: unknown; response?: Response };

/** Turn a generated-client result into data or an ApiError. */
export function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || result.data === undefined) {
    const status = result.response?.status ?? 0;
    throw new ApiError(status, detailOf(result.error, status));
  }
  return result.data;
}

export function detailOf(error: unknown, status?: number): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => {
          const loc = Array.isArray(e?.loc) ? e.loc.slice(1).join(".") : "";
          return loc ? `${loc}: ${e?.msg ?? ""}` : String(e?.msg ?? JSON.stringify(e));
        })
        .join("; ");
    }
    return JSON.stringify(d);
  }
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return status ? `request failed (${status})` : "request failed";
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}
