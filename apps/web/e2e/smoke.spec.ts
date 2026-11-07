import { expect, test } from "@playwright/test";

test("home page loads and reaches the API", async ({ page, request }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Ask a question a dataset can answer/ }),
  ).toBeVisible();
  await expect(page.getByLabel("Your question")).toBeVisible();
  const health = await request.get("http://localhost:8000/api/health");
  expect(await health.json()).toMatchObject({ status: "ok" });
});

test("a session can be opened by id and shows its sections", async ({ page, request }) => {
  const created = await request.post("http://localhost:8000/api/sessions");
  const { id } = await created.json();
  await page.goto(`/s/${id}`);
  await expect(page.getByRole("heading", { name: "Datasets", exact: true })).toBeVisible();
  await expect(page.getByText("No datasets in this session")).toBeVisible();
  await expect(page.getByText("No runs yet")).toBeVisible();
  await request.delete(`http://localhost:8000/api/sessions/${id}`);
});
