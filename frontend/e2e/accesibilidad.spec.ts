import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockApi } from "./mocks";

const PAGES = [
  { name: "Chat", path: "/chat", ready: "Preguntas sugeridas" },
  { name: "Estudio del modelo", path: "/modelo-semantico", ready: "Contexto" },
  { name: "Proveedores", path: "/proveedores-ia", ready: "Simulado" },
];

for (const scheme of ["light", "dark"] as const) {
  for (const { name, path, ready } of PAGES) {
    test(`${name} sin violaciones serias ni críticas (tema ${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await mockApi(page);
      await page.goto(path);
      await expect(page.getByText(ready).first()).toBeVisible();

      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
    });
  }
}
