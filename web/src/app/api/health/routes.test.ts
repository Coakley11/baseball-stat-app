// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

// `connection()` only means something inside a Next.js request; here it is a no-op.
vi.mock("next/server", () => ({ connection: async () => undefined }));

const check = vi.fn();
vi.mock("@/lib/api/readiness", () => ({ READINESS_RETRY_AFTER_S: 5, checkReadiness: (...args: unknown[]) => check(...args) }));

import { GET as ready } from "../ready/route";
import { GET as live } from "./route";

afterEach(() => check.mockReset());

describe("GET /api/health (liveness)", () => {
  it("answers 200 without consulting the Python API", async () => {
    const res = await live();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(check).not.toHaveBeenCalled();
  });
});

describe("GET /api/ready (readiness)", () => {
  it("is 200 when the API is ready", async () => {
    check.mockResolvedValue("ready");
    const res = await ready();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ready" });
    expect(res.headers.get("retry-after")).toBeNull();
  });

  it("is 503 with Retry-After while the API is warming up", async () => {
    check.mockResolvedValue("warming");
    const res = await ready();
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ status: "warming" });
    expect(res.headers.get("retry-after")).toBe("5");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it.each(["unavailable", "not_configured"])("is 503 for %s and carries only the state word", async (state) => {
    check.mockResolvedValue(state);
    const res = await ready();
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ status: state });
    expect(res.headers.get("retry-after")).toBeNull();
  });
});
