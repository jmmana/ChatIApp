# Spike · GitHub Copilot como proveedor de IA

Issue #64 · Épica #5 · Hito M2

## Decisión

**ChatIApp ofrece solo GitHub Models (`github/`). No ofrece la suscripción de Copilot (`github_copilot/`).**

## Límites de esta evaluación

El spike se hizo en un contenedor **sin red, sin token de GitHub y sin LiteLLM instalado**. Por tanto:

- Lo que se dice de `github_copilot/` viene del conocimiento del código de LiteLLM y **no se contrastó** contra la versión 1.111.0 del catálogo. Hay que releer el código antes de citarlo como definitivo.
- **Los términos de uso no se pudieron consultar en vivo.** La sección de términos resume lo conocido y lista qué texto hay que revisar. Quien revise debe confirmarlo antes de aprobar el PR.
- **La prueba de concepto con `github/` no se ejecutó.** Se deja el guion para correrlo en una máquina con red (ver abajo); el criterio queda sin marcar.

## Cómo autentica `github_copilot/` en LiteLLM

1. Flujo de dispositivo OAuth de GitHub con el `client_id` de un cliente de editor (el de la extensión de Copilot), no de una app propia de ChatIApp.
2. El usuario abre `https://github.com/login/device` e introduce un código. LiteLLM lo **imprime en la salida estándar** y sondea hasta que se autoriza.
3. El token de acceso se guarda en disco, por defecto bajo `~/.config/litellm/github_copilot/` (configurable con `GITHUB_COPILOT_TOKEN_DIR`).
4. Ese token se cambia por un token de API de corta duración en un endpoint interno de GitHub (`copilot_internal`), que se renueva solo.
5. Las peticiones van al endpoint de Copilot con cabeceras que se hacen pasar por un editor (`editor-version`, `Copilot-Integration-Id`, etc.).

Consecuencias: el token pertenece a **una persona** con asiento de Copilot; el endpoint interno no es una API pública con contrato; el cliente suplantado es el de otro producto.

## ¿Funciona en un servidor sin navegador?

A medias. El flujo de dispositivo no necesita navegador *en el servidor*: otra persona abre la URL en cualquier equipo. Pero:

- El código se imprime por consola; no hay API para mostrarlo en la interfaz de ChatIApp. Habría que envolver o reimplementar el autenticador.
- El token vive en el disco del servidor, ligado a un solo usuario de GitHub; en un contenedor efímero se pierde.
- Cada usuario de ChatIApp no puede usar *su* suscripción sin un flujo por usuario, que el catálogo no contempla (la configuración es del servidor).

## Términos de uso (por confirmar en vivo)

Textos a revisar: *GitHub Terms for Additional Products and Features* (sección GitHub Copilot), *GitHub Acceptable Use Policies* y la documentación de Copilot sobre uso permitido.

Lo que se conoce y debe confirmarse:

- Copilot se licencia **por usuario**; compartir un asiento entre varias personas no está previsto.
- Se prohíben el uso automatizado excesivo, revender el acceso y eludir los límites del servicio.
- Exponer la cuota de una suscripción personal como backend de una aplicación multiusuario encaja en lo que esas cláusulas buscan evitar. Además depende de un endpoint interno y de suplantar a un editor.

Mientras GitHub no autorice expresamente ese uso, el riesgo (suspensión de la cuenta, rotura sin aviso) recae en el cliente y en ChatIApp.

## GitHub Models (`github/`)

- API oficial para usar modelos desde aplicaciones, con un **token de GitHub** (PAT con permiso `models:read` o token de GitHub Actions).
- Se limita y factura aparte de Copilot: nivel gratuito con límites bajos para prototipos y uso de pago opcional.
- Un token de servicio por organización o proyecto: encaja con el modelo multiusuario de ChatIApp (credencial del servidor, no de una persona).
- Campos en el catálogo: solo el token. El catálogo ya lo lista.

## Prueba de concepto (GitHub Models) — pendiente de ejecutar

Guion para una máquina con red y `GITHUB_TOKEN` con `models:read`. No lo guardes con el token.

```python
import json, os, litellm

plan_prompt = (
    "Devuelve SOLO un plan JSON para: «ventas totales por mes del último año». "
    'Formato: {"metric": str, "group_by": [str], "filters": []}'
)
r = litellm.completion(
    model="github/gpt-4o-mini",  # usa un modelo que liste GitHub Models
    api_key=os.environ["GITHUB_TOKEN"],
    messages=[{"role": "user", "content": plan_prompt}],
    response_format={"type": "json_object"},
)
print(json.loads(r.choices[0].message.content))
```

Criterio de éxito: el JSON se parsea y contiene métrica y agrupación. Anota aquí el resultado, el modelo y la versión de LiteLLM al ejecutarlo.

## Recomendación

1. Soportar `github/` en el catálogo (ya está).
2. No soportar `github_copilot/` en servidores multiusuario. Reabrir si GitHub publica una API de Copilot para terceros o autoriza por escrito ese uso.
3. Antes de cerrar el issue: confirmar los términos en vivo y ejecutar la prueba de concepto.
