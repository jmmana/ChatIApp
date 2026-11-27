# Proveedores de IA

ChatIApp no depende de ningún proveedor. Usa [LiteLLM](https://github.com/BerriAI/litellm) como pasarela única ([ADR 0002](adr/0002-litellm-como-pasarela-de-ia.md)): cada proveedor es una entrada del catálogo con sus campos, y cambiar de uno a otro es configuración.

## Formas de conectarse

| Modo | Cuándo usarlo | Credenciales |
|---|---|---|
| **API directa** | Tienes cuenta con el proveedor del modelo | API key |
| **Plataforma cloud** | Tu empresa ya tiene contrato, facturación y gobierno en AWS, Azure o Google Cloud | Las de la plataforma: IAM, endpoint + key, cuenta de servicio |
| **Agregador** | Quieres probar muchos modelos con una sola cuenta | API key del agregador |
| **Local / compatible con OpenAI** | Los datos no pueden salir de tu red, o quieres costo cero por token | URL del servidor |

## Catálogo

Los prefijos de LiteLLM se verificaron contra **LiteLLM 1.111.0** (`litellm.provider_list`), igual que los endpoints por defecto de los proveedores chinos. Los modelos se **listan en vivo** desde el proveedor cuando su API lo permite; los nombres de abajo son solo ejemplos.

### API directa

| Proveedor | Prefijo LiteLLM | Campos | Ejemplos de modelo |
|---|---|---|---|
| Anthropic (Claude) | `anthropic/` | `api_key` | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` |
| OpenAI (ChatGPT) | `openai/` | `api_key`, `organization` (opcional) | Familia GPT vigente |
| Google Gemini (AI Studio) | `gemini/` | `api_key` | Familia Gemini vigente (Pro, Flash) |
| Mistral | `mistral/` | `api_key` | Mistral Large, Small |
| xAI (Grok) | `xai/` | `api_key` | Familia Grok vigente |
| Groq | `groq/` | `api_key` | Modelos abiertos con inferencia rápida |

### Plataformas cloud

| Plataforma | Prefijo LiteLLM | Campos | Notas |
|---|---|---|---|
| AWS Bedrock | `bedrock/` | `aws_region`, y `aws_access_key_id` + `aws_secret_access_key` **o** rol IAM de la máquina | Claude, Llama, Mistral, Nova y otros; sin llaves se usa la cadena de credenciales de AWS (rol IAM). Perfiles de inferencia entre regiones: usa su id como modelo (`us.anthropic.…`); para perfiles de aplicación, el campo opcional `model_id` lleva el ARN |
| Azure OpenAI | `azure/` | `api_base`, `api_key`, `api_version`, nombre del *deployment* como modelo | El modelo es el nombre de tu deployment, no el del modelo base |
| Azure AI Foundry | `azure_ai/` | `api_base`, `api_key` | Modelos del catálogo de Foundry |
| Google Vertex AI | `vertex_ai/` | `vertex_project`, `vertex_location`, `vertex_credentials` (JSON de la cuenta de servicio, **se guarda como secreto cifrado**) | Gemini y modelos de socios en Vertex |
| OpenRouter | `openrouter/` | `api_key` | Cientos de modelos con una cuenta |
| GitHub Models | `github/` | Token de GitHub con permiso de modelos | Ver [GitHub Copilot](#github-copilot) |

### Modelos chinos

| Proveedor | Prefijo LiteLLM | Endpoint por defecto en LiteLLM | Ejemplos de modelo |
|---|---|---|---|
| DeepSeek | `deepseek/` | `https://api.deepseek.com` | `deepseek-chat`, `deepseek-reasoner` |
| Qwen (Alibaba Cloud Model Studio / DashScope) | `dashscope/` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (internacional) | `qwen-max`, `qwen-plus`, `qwen-turbo` |
| Kimi (Moonshot AI) | `moonshot/` | `https://api.moonshot.ai/v1` | Familia Kimi vigente |
| GLM (Z.ai / Zhipu) | `zai/` | `https://api.z.ai/api/paas/v4` | Familia GLM vigente |
| MiniMax | `minimax/` | `https://api.minimax.io/v1` | Familia MiniMax vigente |
| Doubao (ByteDance Volcengine Ark) | `volcengine/` | `https://ark.cn-beijing.volces.com/api/v3` | Modelos Doubao (el modelo suele ser el id del endpoint) |

Cada uno permite cambiar `api_base` para usar el endpoint de **China continental** en lugar del internacional. El catálogo ([`backend/app/llm/catalog.py`](../backend/app/llm/catalog.py)) los ofrece como opciones de `api_base`: Qwen `https://dashscope.aliyuncs.com/compatible-mode/v1`, Kimi `https://api.moonshot.cn/v1`, GLM `https://open.bigmodel.cn/api/paas/v4`, MiniMax `https://api.minimaxi.com/v1`; DeepSeek y Doubao tienen un único endpoint. **Pendiente de confirmar** contra la documentación oficial de cada proveedor desde una máquina con red.

### Local y compatible con OpenAI

| Servidor | Prefijo LiteLLM | Campos |
|---|---|---|
| Ollama | `ollama_chat/` | `api_base` (por defecto `http://localhost:11434`), `api_key` opcional |
| vLLM | `hosted_vllm/` | `api_base`, `api_key` opcional |
| LM Studio | `lm_studio/` | `api_base`, `api_key` opcional |
| Cualquier servidor compatible con OpenAI | `openai/` + `api_base` | `api_base`, `api_key` opcional |

Los modelos se listan desde `GET {api_base}/api/tags` en Ollama y desde `GET {api_base}/models` (`/v1/models`) en los demás; la `api_key`, si existe, se envía como `Bearer`. Con `docker compose --profile local-ai up`, Ollama queda en `http://ollama:11434` dentro de la red de Compose (descarga un modelo con `docker compose exec ollama ollama pull llama3.1`).

## GitHub Copilot

Hay dos caminos y no son equivalentes:

| Camino | Qué es | Estado en ChatIApp |
|---|---|---|
| **GitHub Models** (`github/`) | API oficial de GitHub para usar modelos desde aplicaciones, con un token de GitHub | Soportado en el catálogo |
| **Suscripción de Copilot** (`github_copilot/`) | LiteLLM trae este proveedor, que se autentica con tu suscripción de Copilot por flujo de dispositivo OAuth | **No se ofrece** (decisión del spike): el token es de una persona, depende de un endpoint interno y los términos de GitHub no contemplan servir una suscripción a varios usuarios. Detalle y condiciones para reabrirlo en [docs/spikes/github-copilot.md](spikes/github-copilot.md) |

**Decisión:** ChatIApp ofrece solo GitHub Models. Siguen pendientes, sin verificar, de una máquina con red (issue #173): el flujo de autenticación de `github_copilot/` contra LiteLLM 1.111.0, la lectura de los términos de uso y la prueba de concepto con `github/`. El spike trae los guiones.

## Enrutamiento por tarea

No todas las tareas necesitan el mismo modelo. Cada una puede ir a un proveedor distinto:

| Tarea | Qué hace | Qué necesita del modelo | Sugerencia |
|---|---|---|---|
| `planner` | Entiende la pregunta y devuelve el plan JSON | Razonamiento y JSON confiable | Modelo fuerte |
| `sql` | Escribe SQL cuando no hay métrica en el catálogo | Fuerte en código y dialectos | Modelo fuerte |
| `answer` | Redacta 2 a 4 frases con el resultado | Buena redacción, rápido | Modelo económico o local |
| `suggest` | Sugiere descripciones y sinónimos del modelo semántico | Lotes, no es urgente | Modelo económico o local |

```yaml
ai:
  routing:
    planner: claude
    sql: claude
    answer: deepseek
    suggest: local
    fallback: [deepseek, local]
```

**Respaldo (fallback):** si el proveedor de una tarea falla por autenticación, cuota, tiempo de espera o error 5xx, se intenta el siguiente de `fallback` y queda registrado en el razonamiento («Claude no respondió; usé DeepSeek»). Un plan **inválido** no dispara el respaldo: se reintenta con el mismo proveedor y el error. Tampoco `model_not_found`: es un error de configuración. Sin asignación, la tarea usa el proveedor predeterminado. El orquestador emite un `step` con `status: warning` por cada respaldo. La asignación se guarda con `PUT /api/v1/providers/routing` o se declara en `chatiapp.yaml`; la implementación está en `backend/app/llm/routing.py`.

## Probar conexión

El botón **Probar conexión** (y `POST /api/v1/providers/{id}/test`) hace una llamada mínima y responde:

| Resultado | Significa |
|---|---|
| ✅ Conectado · 840 ms | Respondió; muestra la latencia |
| 🔑 Credenciales inválidas | 401/403 del proveedor |
| 💳 Sin cuota o sin saldo | 429 o error de facturación |
| 🔍 Modelo no encontrado | El modelo no existe o tu cuenta no tiene acceso |
| 🌐 Sin conexión | DNS, TLS, proxy o `api_base` equivocada |

También se puede probar **antes de guardar**, con los datos del formulario.

## Qué ve el modelo de IA

Se configura por fuente de datos. El administrador fija el máximo permitido.

| Nivel | El modelo recibe | La respuesta final |
|---|---|---|
| `schema` | Pregunta, historial y modelo semántico **sin** valores de ejemplo. Nunca filas | Se arma con una plantilla local («Vendiste $482,3 M en noviembre») sin enviar el resultado |
| `aggregates` *(por defecto)* | Lo anterior + el resultado de la consulta si tiene ≤ 50 filas | La redacta el modelo |
| `samples` | Lo anterior + `sample_values` de las columnas | La redacta el modelo |

Las columnas ocultas nunca salen, en ningún nivel. Detalle en [SEGURIDAD.md](SEGURIDAD.md#qué-ve-el-modelo-de-ia).

## Credenciales

- Se guardan **cifradas** (Fernet) en la base de la app con la llave `CHATIAPP_SECRET_KEY`; se rotan con `CHATIAPP_SECRET_KEY_PREVIOUS` (MultiFernet).
- La API **nunca** las devuelve: solo una máscara (`sk-…a1b2`).
- No se escriben en logs ni en la auditoría.
- En `chatiapp.yaml` se referencian como `${VARIABLE}`; nunca en claro.

## Costo y uso

Cada llamada registra tokens de entrada y salida, latencia y costo estimado (con la tabla de precios de LiteLLM) en la auditoría del turno. La interfaz muestra el costo de cada respuesta y el acumulado por proveedor.
