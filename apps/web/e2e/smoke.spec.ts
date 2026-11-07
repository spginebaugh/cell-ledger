import { expect, test } from "@playwright/test";

test("home page loads and reaches the API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "cell-ledger" })).toBeVisible();
  await expect(page.getByTestId("api-status")).toHaveText(/API ok/);
});
