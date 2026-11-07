import { expect, test } from "@playwright/test";

test("home page loads and reaches the API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "cell-ledger" })).toBeVisible();
  await expect(page.getByTestId("api-status")).toHaveText(/API ok/);
});

test("out-of-scope request shows a reason and downloadable bundle", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("What are you investigating?").fill("mouse single-cell");
  await page.getByRole("button", { name: "Find studies" }).click();
  await expect(page.getByText("unsupported", { exact: true })).toBeVisible();
  await expect(page.getByText(/outside human bulk RNA-seq/)).toBeVisible();
  await page.reload();
  await expect(page.getByText("unsupported", { exact: true })).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download run bundle" }).click();
  expect((await downloadEvent).suggestedFilename()).toMatch(/cell-ledger-.*\.zip/);
});

test("clarification uses source labels and reveals sample evidence", async ({ page }) => {
  let answered = false;
  await page.route("**/api/runs", (route) =>
    route.fulfill({ json: { id: "fixture" }, status: 202 }),
  );
  await page.route("**/api/runs/fixture", (route) =>
    route.fulfill({
      json: {
        id: "fixture",
        status: answered ? "complete" : "running",
        events: [],
        questions: "",
        pending_question: answered ? null : { gse: "GSE1", options: ["treated", "mock"] },
        manifest: {
          datasets: answered
            ? [
                {
                  gse: "GSE1",
                  title: "Synthetic browser fixture",
                  status: "needs_review",
                  reasons: ["Donor independence unresolved"],
                  samples: 1,
                },
              ]
            : [],
        },
      },
    }),
  );
  await page.route("**/api/runs/fixture/answer", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      case: "treated",
      control: "mock",
      skip: false,
    });
    answered = true;
    await route.fulfill({ json: { accepted: true } });
  });
  await page.route("**/api/runs/fixture/samples/GSE1", (route) =>
    route.fulfill({
      json: [
        {
          gsm: "GSM1",
          group: "case",
          condition: "treated",
          evidence: JSON.stringify({ condition: { evidence: "condition: treated" } }),
        },
      ],
    }),
  );
  await page.goto("/");
  await page.getByLabel("What are you investigating?").fill("human IFNG");
  await page.getByRole("button", { name: "Find studies" }).click();
  await page.getByLabel("Choose case").selectOption("treated");
  await page.getByLabel("Choose control").selectOption("mock");
  await page.getByRole("button", { name: "Use these groups" }).click();
  await page.getByText("Inspect samples and evidence").click();
  await expect(page.getByRole("cell", { name: "condition: treated", exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/evidence-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/evidence-mobile.png", fullPage: true });
});
