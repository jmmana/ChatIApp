/** Fragmentos de integración con la URL de la instalación (docs/INTEGRACION.md). */

export function backendSnippet(baseUrl: string): string {
  return `# Tu backend: cambia la API key por un token de sesión de 15 minutos
r = httpx.post(
    "${baseUrl}/api/v1/embed/sessions",
    headers={"Authorization": f"Bearer {CHATIAPP_API_KEY}"},  # variable de entorno del servidor
    json={
        "datasource": "ventas",
        "origin": "https://tu-app.example.com",
        "user": {"id": session.user_id, "role": "gerente_sucursal"},
    },
)
token = r.json()["token"]`;
}

export function widgetSnippet(baseUrl: string): string {
  return `<script src="${baseUrl}/embed/v1/chatiapp.js" defer></script>

<chatiapp-chat base-url="${baseUrl}" lang="es" theme="auto"></chatiapp-chat>

<script>
  document.querySelector("chatiapp-chat").getToken = async () => {
    const r = await fetch("/chatiapp-token", { method: "POST", credentials: "include" });
    return (await r.json()).token;
  };
</script>`;
}
