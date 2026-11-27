import { expect, test } from "@playwright/test";
import { mockApi } from "./mocks";

test("«¿Cuánto vendí?» → «Este mes» se completa solo con teclado", async ({ page }) => {
  await mockApi(page);
  await page.goto("/chat");

  const question = page.getByRole("textbox", { name: "Pregunta" });
  await expect(question).toBeEnabled();
  // Se llega al campo con Tab desde el principio de la página, sin ratón.
  for (let i = 0; i < 40 && !(await question.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(question).toBeFocused();

  await page.keyboard.type("¿Cuánto vendí?");
  await page.keyboard.press("Enter");

  // El foco pasa a las opciones de aclaración; se recorren con las flechas y se eligen con Enter.
  await expect(page.getByRole("group", { name: "¿De qué periodo?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Este mes", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Mes pasado", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");

  await expect(page.getByText("Este mes vendiste 1.250.000.")).toBeVisible();
});
