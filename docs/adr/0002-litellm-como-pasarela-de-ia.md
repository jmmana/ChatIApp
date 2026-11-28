# ADR 0002 · LiteLLM como pasarela de IA

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

ChatIApp debe funcionar con Claude, ChatGPT, Gemini, modelos chinos (DeepSeek, Qwen, Kimi, GLM, MiniMax, Doubao), plataformas cloud (Bedrock, Azure, Vertex AI, OpenRouter) y modelos locales. Cada uno tiene su SDK, su autenticación, su formato de *streaming*, de salida estructurada y de errores.

## Decisión

Usar [LiteLLM](https://github.com/BerriAI/litellm) como **librería** (no como proxy separado) detrás de una pasarela propia (`app/llm/gateway.py`) que expone tres operaciones: completar texto, completar JSON y *streaming*. La pasarela agrega lo que LiteLLM no decide por nosotros: catálogo de proveedores con sus campos, cifrado de credenciales, enrutamiento por tarea, respaldo, clasificación de errores y registro de tokens y costo.

Se verificó con LiteLLM 1.111.0 que todos los prefijos del catálogo existen en `litellm.provider_list`: `anthropic`, `openai`, `gemini`, `vertex_ai`, `bedrock`, `azure`, `azure_ai`, `deepseek`, `dashscope`, `moonshot`, `volcengine`, `zai`, `minimax`, `mistral`, `xai`, `groq`, `openrouter`, `ollama_chat`, `github`, `github_copilot`, `hosted_vllm`, `lm_studio`.

## Consecuencias

- ✅ Agregar un proveedor es una entrada en el catálogo, no un adaptador nuevo.
- ✅ Errores con forma común (autenticación, cuota, modelo inexistente, tiempo de espera) para la prueba de conexión y el respaldo.
- ✅ Cálculo de costo por llamada con la tabla de precios de LiteLLM.
- ⚠️ Dependemos del ritmo de LiteLLM. Se fija la versión y la pasarela aísla el resto del código de su API.
- ⚠️ No todos los proveedores soportan salida JSON estricta; la pasarela pide JSON por instrucciones, lo valida con Pydantic y reintenta una vez con el error.

## Alternativas consideradas

- **SDK de cada proveedor.** Máximo control, pero un adaptador por proveedor y meses de mantenimiento.
- **Solo la API compatible con OpenAI.** Muchos proveedores la ofrecen, pero no Bedrock ni Vertex con sus credenciales nativas, y cada compatibilidad tiene matices.
- **LiteLLM como proxy aparte.** Útil para organizaciones grandes; agrega un servicio más. Queda como opción de despliegue, no como requisito.
