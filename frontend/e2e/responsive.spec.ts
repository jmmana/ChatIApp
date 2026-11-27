import { expect, test } from "@playwright/test";
import { mockApi } from "./mocks";

test.use({ viewport: { width: 375, height: 700 } });

test("a 375 px no hay desbordamiento horizontal y la barra lateral pasa a un menú", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/chat");
  await expect(page.getByRole("list", { name: "Preguntas sugeridas" })).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);

  // La barra lateral fija no se ve; la navegación vive en el menú.
  await expect(page.getByRole("navigation", { name: "Principal" })).toBeHidden();
  await page.getByRole("button", { name: "Abrir menú" }).click();
  const nav = page.getByRole("dialog").getByRole("navigation", { name: "Principal" });
  await expect(nav).toBeVisible();
  await nav.getByRole("link", { name: "Proveedores de IA" }).click();
  await expect(page).toHaveURL(/\/proveedores-ia$/);
});

test("a 375 px las conversaciones se abren desde un menú", async ({ page }) => {
  await mockApi(page);
  await page.goto("/chat");
  await page.getByRole("button", { name: "Conversaciones" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: /Nueva conversación/ })).toBeVisible();
});
