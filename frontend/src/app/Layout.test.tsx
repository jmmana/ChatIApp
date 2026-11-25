import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { appRoutes } from "./routes";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  it("muestra la barra lateral con las seis secciones", () => {
    renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const title of [
      "Chat",
      "Modelo semántico",
      "Proveedores de IA",
      "Fuentes de datos",
      "Auditoría",
      "Evaluación",
    ]) {
      expect(within(nav).getByRole("link", { name: title })).toBeInTheDocument();
    }
  });

  it("redirige la raíz al chat", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { level: 1, name: "Chat" })).toBeInTheDocument();
  });

  it("cada ruta muestra un estado vacío con su título", async () => {
    renderAt("/chat");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const route of appRoutes) {
      await userEvent.click(within(nav).getByRole("link", { name: route.title }));
      expect(screen.getByRole("heading", { level: 1, name: route.title })).toBeInTheDocument();
    }
  });
});
