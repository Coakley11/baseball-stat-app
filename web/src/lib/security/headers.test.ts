// @vitest-environment node
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER } from "next/constants";
import { afterEach, describe, expect, it, vi } from "vitest";

import config from "../../../next.config";

async function headersFor(phase: string): Promise<Map<string, string>> {
  const rules = await config(phase).headers!();
  expect(rules).toHaveLength(1);
  expect(rules[0]!.source).toBe("/:path*");
  return new Map(rules[0]!.headers.map((h) => [h.key, h.value]));
}

function directives(csp: string): Map<string, string> {
  return new Map(csp.split(";").map((d) => d.trim()).map((d) => [d.split(" ")[0]!, d]));
}

afterEach(() => vi.unstubAllEnvs());

describe("security headers", () => {
  it("sets the full header set on a production build", async () => {
    const h = await headersFor(PHASE_PRODUCTION_BUILD);
    expect([...h.keys()].sort()).toEqual(
      [
        "Content-Security-Policy",
        "Cross-Origin-Opener-Policy",
        "Permissions-Policy",
        "Referrer-Policy",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
      ].sort(),
    );
    expect(h.get("X-Content-Type-Options")).toBe("nosniff");
    expect(h.get("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    expect(h.get("X-Frame-Options")).toBe("DENY");
    expect(h.get("Permissions-Policy")).toContain("camera=()");
    expect(h.get("Permissions-Policy")).toContain("geolocation=()");
    expect(h.get("Strict-Transport-Security")).toBe("max-age=31536000");
  });

  it("keeps the production CSP closed: same-origin only, no eval, no framing, no plugins", async () => {
    const csp = directives((await headersFor(PHASE_PRODUCTION_SERVER)).get("Content-Security-Policy")!);
    expect(csp.get("default-src")).toBe("default-src 'self'");
    expect(csp.get("script-src")).toBe("script-src 'self' 'unsafe-inline'");
    expect(csp.get("connect-src")).toBe("connect-src 'self'");
    expect(csp.get("frame-ancestors")).toBe("frame-ancestors 'none'");
    expect(csp.get("object-src")).toBe("object-src 'none'");
    expect(csp.get("base-uri")).toBe("base-uri 'self'");
    expect(csp.get("form-action")).toBe("form-action 'self'");
    const text = [...csp.values()].join(";");
    expect(text).not.toContain("unsafe-eval");
    expect(text).not.toMatch(/\*|https?:/); // no wildcard and no external origin is allowed
  });

  it("allows eval and omits HSTS in development only", async () => {
    const h = await headersFor(PHASE_DEVELOPMENT_SERVER);
    expect(h.get("Content-Security-Policy")).toContain("'unsafe-eval'");
    expect(h.has("Strict-Transport-Security")).toBe(false);
    expect(h.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
  });

  it("drops HSTS for a production build that is not served over HTTPS", async () => {
    vi.stubEnv("BASEBALL_WEB_HSTS", "off");
    const h = await headersFor(PHASE_PRODUCTION_BUILD);
    expect(h.has("Strict-Transport-Security")).toBe(false);
    expect(h.has("Content-Security-Policy")).toBe(true);
  });
});
