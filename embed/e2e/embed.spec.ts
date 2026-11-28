import { createRequire } from "node:module";
import type { Page } from "@playwright/test";

// Ver playwright.config.ts: Node no ve las exportaciones con nombre de @playwright/test como ESM.
const { expect, test } = createRequire(import.meta.url)(
  "@playwright/test",
) as typeof import("@playwright/test");

const CHATIAPP = "http://localhost:4101";
const HOST = "http://localhost:4102";

/** Estilos computados de los elementos de la página anfitriona (fuera del widget). */
async function hostStyles(page: Page) {
  return page.evaluate(() => {
    const pick = (selector: string) => {
      const style = getComputedStyle(document.querySelector(selector) as Element);
      return {
        font: style.fontFamily,
        size: style.fontSize,
        color: style.color,
        background: style.backgroundColor,
        border: style.borderTopWidth + " " + style.borderTopColor,
        margin: style.margin,
      };
    };
    return {
      body: pick("body"),
      titulo: pick("#titulo"),
      parrafo: pick("#parrafo"),
      fuera: pick("#fuera"),
    };
  });
}

test("una página de otro origen embebe el widget, pregunta y recibe la respuesta", async ({
  page,
}) => {
  await page.goto("/");
  const textarea = page.locator("chatiapp-chat textarea");
  await expect(textarea).toBeVisible();
  const before = await hostStyles(page);

  await textarea.fill("ventas de hoy");
  await textarea.press("Enter");
  await expect(page.locator("chatiapp-chat").getByText("Vendiste 10.")).toBeVisible();

  // El evento DOM llega a la página, que lo usa para su analítica.
  const events = await page.evaluate(() => (window as unknown as { __events: unknown[] }).__events);
  expect(events).toEqual([
    {
      name: "answer",
      detail: expect.objectContaining({ text: "Vendiste 10.", conversationId: "c1" }),
    },
  ]);

  // ChatIApp vio el origen de la página y el token que le dio su backend, no una cookie.
  const requests = await (await page.request.get(`${CHATIAPP}/__requests`)).json();
  expect(requests).toHaveLength(1);
  expect(requests[0].origin).toBe(HOST);
  expect(requests[0].authorization).toMatch(/^Bearer .+\..+\..+$/);
  expect(requests[0].body).toMatchObject({
    datasource_id: "11111111-1111-4111-8111-111111111111",
    message: "ventas de hoy",
  });

  // Los estilos de la página no cambian por tener el widget (y a la inversa).
  expect(await hostStyles(page)).toEqual(before);
});

test("los estilos de la página no se filtran al widget y sus variables --chatiapp-* sí aplican", async ({
  page,
}) => {
  await page.goto("/");
  const inside = page.locator("chatiapp-chat textarea");
  await expect(inside).toBeVisible();
  // La página pinta todo `textarea` de amarillo con borde azul: el del widget no lo hereda…
  const style = await inside.evaluate((el) => {
    const s = getComputedStyle(el);
    return { background: s.backgroundColor, border: s.borderTopColor };
  });
  expect(style.background).not.toBe("rgb(255, 255, 0)");
  expect(style.border).not.toBe("rgb(0, 0, 255)");
  // …mientras que el de la página sí lo conserva.
  await expect(page.locator("#fuera")).toHaveCSS("background-color", "rgb(255, 255, 0)");

  // El acento sale de --chatiapp-accent, definida en la página.
  const send = page.locator("chatiapp-chat").getByRole("button", { name: "Enviar" });
  await expect(send).toHaveCSS("background-color", "rgb(200, 30, 90)");
});

test("pide otro token cuando el servidor lo rechaza, sin perder la conversación", async ({
  page,
}) => {
  let first = true;
  await page.route(`${CHATIAPP}/api/v1/chat/stream`, async (route) => {
    // La primera petición con el token inicial «vence»; el widget debe pedir otro y reintentar.
    if (first && route.request().method() === "POST") {
      first = false;
      return route.fulfill({
        status: 401,
        headers: { "Access-Control-Allow-Origin": HOST },
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "token_expired" } }),
      });
    }
    return route.fallback();
  });
  await page.goto("/");
  const tokens: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/chatiapp-token")) tokens.push(request.url());
  });
  const textarea = page.locator("chatiapp-chat textarea");
  await textarea.fill("ventas de hoy");
  await textarea.press("Enter");
  await expect(page.locator("chatiapp-chat").getByText("Vendiste 10.")).toBeVisible();
  expect(tokens.length).toBeGreaterThanOrEqual(2);
});
