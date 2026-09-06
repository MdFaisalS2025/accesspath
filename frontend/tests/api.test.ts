import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, compareRoutes, fetchSegments } from "../src/api/client";

function mockFetchOnce(status: number, body: unknown, ok = status < 400) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: async () => body,
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("returns a parsed successful route comparison", async () => {
    const body = { status: "ok", routes: {} };
    mockFetchOnce(200, body);
    const result = await compareRoutes(47.6, -122.33, 47.61, -122.32);
    expect(result).toEqual(body);
  });

  it("throws ApiError with status/body for a 400 response", async () => {
    mockFetchOnce(400, { error: "out_of_service_area", message: "nope" }, false);
    await expect(compareRoutes(1, 2, 3, 4)).rejects.toMatchObject({
      status: 400,
      body: { error: "out_of_service_area" },
    });
  });

  it("throws ApiError with status 0 when fetch itself rejects (server unreachable)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(compareRoutes(1, 2, 3, 4)).rejects.toBeInstanceOf(ApiError);
    await expect(compareRoutes(1, 2, 3, 4)).rejects.toMatchObject({ status: 0 });
  });

  it("builds the bbox query string for map endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ type: "FeatureCollection", features: [], count: 0, truncated: false }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await fetchSegments([-122.35, 47.61, -122.34, 47.62]);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/segments?bbox=-122.35,47.61,-122.34,47.62"),
      expect.anything(),
    );
  });
});
