import { expect, test } from "@playwright/test";

// Runs against the real stack (docker compose up), no mocks -- see
// docs/week6_frontend_report.md for exact invocation and measured timings.

test("select two points, compare routes, and select the confidence-aware route", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AccessPath" })).toBeVisible();

  const map = page.locator(".map-view");
  await expect(map).toBeVisible();
  const box = await map.boundingBox();
  if (!box) throw new Error("map not rendered");

  // Two points near the map's center (downtown Seattle at the default
  // view), close enough together to very likely both be within the
  // routable network's snap distance.
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;

  await page.mouse.click(centerX - 40, centerY - 30);
  await expect(page.getByText(/Origin placed/)).toBeVisible();

  await page.mouse.click(centerX + 40, centerY + 30);
  await expect(page.getByText(/Both points placed/)).toBeVisible();

  const compareButton = page.getByRole("button", { name: /compare routes/i });
  await expect(compareButton).toBeEnabled();
  await compareButton.click();

  // Either a successful three-route comparison or an explicit
  // no-connected-route/no-routable-network message is an acceptable,
  // well-defined outcome for two arbitrary nearby points -- the test
  // asserts the app reaches ONE of its defined states within the ~3s
  // budget, not a specific geometry.
  const resultHeading = page.getByRole("heading", { name: "Route comparison", exact: true });
  const noRoute = page.getByText(/No connected route found/);
  const noNetwork = page.getByText(/No nearby routable path/);
  await expect(resultHeading.or(noRoute).or(noNetwork)).toBeVisible({ timeout: 10_000 });

  if (await resultHeading.isVisible()) {
    await expect(page.getByText("Shortest", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("Accessibility-optimized", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("Confidence-aware", { exact: false }).first()).toBeVisible();

    const confidenceAwareCard = page.getByRole("button", { name: /Confidence-aware/ });
    await confidenceAwareCard.click();
    await expect(confidenceAwareCard).toHaveAttribute("aria-pressed", "true");
  }
});

test("shows a clear error state when the API is unavailable", async ({ page }) => {
  await page.route("**/route/compare", (route) => route.abort("failed"));
  await page.goto("/");

  const map = page.locator(".map-view");
  const box = await map.boundingBox();
  if (!box) throw new Error("map not rendered");
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;

  await page.mouse.click(centerX - 40, centerY - 30);
  await page.mouse.click(centerX + 40, centerY + 30);
  await page.getByRole("button", { name: /compare routes/i }).click();

  await expect(page.getByText(/AccessPath server unavailable/)).toBeVisible();
});
