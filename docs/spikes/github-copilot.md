# Spike · GitHub Copilot como proveedor de IA

Issues #64 y #173 · Épica #5 · Hito M2

## Decisión

**ChatIApp no ofrece la suscripción de Copilot (`github_copilot/`) ni GitHub Models (`github/`).**

- **GitHub Models está retirado.** La página oficial dice que desde el 30 de julio de 2026 «the playground, model catalog, inference API, and bring your own key (BYOK) are no longer available to any customer». La recomendación anterior («ofrecer solo GitHub Models») ya no se puede cumplir.
- **`github_copilot/` no se ofrece** como proveedor de un servidor multiusuario: el acceso es de una sola persona, LiteLLM se presenta como el editor oficial y los términos de GitHub no contemplan servir una suscripción a otros usuarios (detalle abajo).
- Para modelos de la nube, las opciones soportadas son las API directas del [hub de proveedores](../PROVEEDORES_IA.md) (Claude, ChatGPT, Gemini, etc.) o modelos locales con Ollama.

## Verificación (27 de noviembre de 2026)

| Criterio | Estado | Detalle |
|---|---|---|
| Versión de LiteLLM fijada | Verificada | `backend/uv.lock` fija **litellm 1.111.0**; el código se leyó del paquete instalado con `uv sync --locked` |
| Flujo de autenticación contra el código de 1.111.0 | **Verificado** | Ver «Cómo autentica `github_copilot/`» |
| Términos de uso vigentes | **Leídos en línea** | Ver «Términos de uso» (fecha de consulta, enlaces y límites de la lectura) |
| GitHub Models | **Retirado** | Ver «GitHub Models» |
| Recomendación | Actualizada | Ver «Decisión» |
| Prueba de concepto con token real | Pendiente (dueño) | Solo aplica a `github_copilot/` y es opcional: la decisión no depende de ella |

## Cómo autentica `github_copilot/` en LiteLLM 1.111.0

Contrastado con `litellm/llms/github_copilot/` (`authenticator.py`, `common_utils.py`):

- **Flujo de dispositivo OAuth** con un `client_id` de editor (`DEFAULT_GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"`, sobreescribible con `GITHUB_COPILOT_CLIENT_ID`), contra `https://github.com/login/device/code` y `https://github.com/login/oauth/access_token`.
- **Endpoint interno** `https://api.github.com/copilot_internal/user` para resolver la URL base; las llamadas de modelo van a `https://api.githubcopilot.com`.
- **Se hace pasar por el editor oficial:** envía `editor-version: vscode/1.85.1` y `user-agent: GithubCopilot/1.155.0`.
- El token se guarda en un archivo (`GITHUB_COPILOT_TOKEN_DIR`, archivo `access-token`) y se reutiliza.
- **No puede iniciar sesión dentro de un servidor en marcha:** si se pide el token desde un bucle de eventos o un hilo de trabajo (el caso de ChatIApp con FastAPI o del proxy de LiteLLM), lanza `GetAccessTokenError` y pide iniciar sesión una vez fuera y montar el archivo del token.

## ¿Funciona en un servidor sin navegador?

A medias. El flujo de dispositivo no necesita navegador *en el servidor*: otra persona abre la URL en cualquier equipo. Pero:

- El código se imprime por consola y el inicio de sesión no puede hacerse dentro del servidor (ver arriba): habría que hacerlo aparte y montar el archivo del token.
- El token está ligado a **un solo usuario de GitHub** y vive en el disco del servidor; en un contenedor efímero se pierde.
- Cada usuario de ChatIApp no puede usar *su* suscripción sin un flujo por usuario, que el catálogo no contempla (la configuración es del servidor).

## Términos de uso

Consultados en línea el **27 de noviembre de 2026**:

| Fuente | Qué dice | Relevancia |
|---|---|---|
| [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service), sección J («AI Features, Training, and Your Data») | Regula propiedad de entradas y salidas, uso de entradas y salidas para entrenar modelos («unless you opt out»), descargos y responsabilidad del usuario | **No dice nada sobre aplicaciones de terceros ni uso multiusuario.** Sí implica que, con una suscripción individual, los datos enviados pueden usarse para entrenar salvo que la persona lo desactive |
| [GitHub Terms for Additional Products and Features](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features), sección «GitHub Copilot» (vigente desde el 27 de agosto de 2026) | Remite a los *Generative AI Services Terms* (Business y Enterprise), a los términos de Microsoft o a la sección J | Sin mención de API, proxies o terceros |
| [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies), secciones 4 a 6 | Prohíbe actividad automatizada masiva excesiva, el acceso no autorizado a un servicio y «reproduce, duplicate, copy, sell, resell or exploit any portion of the Service» sin permiso escrito | Es lo más cercano a nuestro caso y **apunta en contra** de repartir el acceso de una persona entre varios usuarios. Es una lectura nuestra, no una conclusión legal |

**Lo que no se leyó:** los *GitHub Generative AI Services Terms* (`github.com/customer-terms/github-generative-ai-services-terms`), los *Product Terms* de Microsoft y la documentación de Copilot sobre acceso programático. Ninguna de las páginas leídas permite ni prohíbe expresamente el uso con LiteLLM; para una respuesta firme habría que confirmarlo con GitHub Support.

**Conclusión:** no hay base para ofrecer `github_copilot/` a varios usuarios; la combinación de un `client_id` y cabeceras de editor ajenos, un endpoint interno y la AUP (sección 6) lo hace una apuesta frágil.

## GitHub Models

Retirado el 30 de julio de 2026 (fuente: <https://docs.github.com/en/github-models>, consultada el 27 de noviembre de 2026). GitHub lo describe como un servicio aparte de Copilot y sugiere Azure AI Foundry. Por tanto:

- La prueba de concepto con `github/` ya no es posible ni necesaria.
- Si el catálogo de proveedores aún lista `github/`, debe retirarse (seguimiento en el issue de limpieza).

## Prueba de concepto opcional (solo `github_copilot/`, la hace el dueño)

Solo tiene sentido para uso personal de una sola persona, nunca para un servidor compartido. Con la versión fijada de LiteLLM, fuera del servidor:

```bash
cd backend && uv sync --locked
uv run python -c "from litellm.llms.github_copilot.authenticator import Authenticator; Authenticator().get_access_token()"
# abre la URL que imprime, escribe el código y autoriza; el token queda en GITHUB_COPILOT_TOKEN_DIR
uv run python -c "import litellm; print(litellm.completion(model='github_copilot/gpt-4o', messages=[{'role':'user','content':'Di hola'}]).choices[0].message.content)"
```

No guardes el token en el repositorio.

## Recomendación

1. No ofrecer `github_copilot/` ni `github/` en el hub de proveedores.
2. Retirar `github/` del catálogo y de la documentación si todavía aparece.
3. Para quien no quiera pagar API de nube: Ollama (local) o las API directas del hub.
4. Reabrir solo si GitHub publica un acceso programático oficial para aplicaciones de terceros.
