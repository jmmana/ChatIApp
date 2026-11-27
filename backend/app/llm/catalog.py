"""Catálogo de proveedores de IA como datos (docs/PROVEEDORES_IA.md#catálogo).

Agregar un proveedor es agregar una entrada a `CATALOG`: la API y la interfaz leen estos datos
y no necesitan código nuevo.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Category = Literal["api", "platform", "chinese", "local"]
FieldType = Literal["text", "secret", "url", "select", "json"]


class FieldOption(BaseModel):
    """Valor permitido (`select`) o alternativo (`url`) de un campo."""

    model_config = ConfigDict(frozen=True)

    value: str
    label: str


class ProviderField(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    type: FieldType = "text"
    required: bool = True
    default: str | None = None
    help: str | None = None
    options: tuple[FieldOption, ...] = ()


class ProviderSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    label: str
    category: Category
    litellm_prefix: str
    fields: tuple[ProviderField, ...]
    suggested_models: tuple[str, ...] = ()
    docs_url: str
    notes: str | None = None


def _api_key(required: bool = True) -> ProviderField:
    return ProviderField(
        name="api_key",
        label="API key",
        type="secret",
        required=required,
        help=None if required else "Opcional: solo si el servidor la exige.",
    )


def _api_base(
    default: str | None,
    *,
    required: bool = True,
    options: tuple[FieldOption, ...] = (),
    help: str | None = None,
) -> ProviderField:
    return ProviderField(
        name="api_base",
        label="URL base (api_base)",
        type="url",
        required=required,
        default=default,
        help=help,
        options=options,
    )


_CHINA_HELP = "Usa el endpoint de China continental si tu cuenta es de la plataforma china."

CATALOG: tuple[ProviderSpec, ...] = (
    # --- API directa ---
    ProviderSpec(
        kind="anthropic",
        label="Anthropic (Claude)",
        category="api",
        litellm_prefix="anthropic/",
        fields=(_api_key(),),
        suggested_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        docs_url="https://docs.anthropic.com/en/api/overview",
    ),
    ProviderSpec(
        kind="openai",
        label="OpenAI (ChatGPT)",
        category="api",
        litellm_prefix="openai/",
        fields=(
            _api_key(),
            ProviderField(name="organization", label="Organización", required=False),
        ),
        suggested_models=("gpt-4o", "gpt-4o-mini"),
        docs_url="https://platform.openai.com/docs/models",
        notes="Los modelos se listan en vivo; estos son solo ejemplos.",
    ),
    ProviderSpec(
        kind="gemini",
        label="Google Gemini (AI Studio)",
        category="api",
        litellm_prefix="gemini/",
        fields=(_api_key(),),
        suggested_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        docs_url="https://ai.google.dev/gemini-api/docs/models",
    ),
    ProviderSpec(
        kind="mistral",
        label="Mistral",
        category="api",
        litellm_prefix="mistral/",
        fields=(_api_key(),),
        suggested_models=("mistral-large-latest", "mistral-small-latest"),
        docs_url="https://docs.mistral.ai/getting-started/models/",
    ),
    ProviderSpec(
        kind="xai",
        label="xAI (Grok)",
        category="api",
        litellm_prefix="xai/",
        fields=(_api_key(),),
        suggested_models=("grok-4", "grok-3-mini"),
        docs_url="https://docs.x.ai/docs/models",
    ),
    ProviderSpec(
        kind="groq",
        label="Groq",
        category="api",
        litellm_prefix="groq/",
        fields=(_api_key(),),
        suggested_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
        docs_url="https://console.groq.com/docs/models",
        notes="Modelos abiertos con inferencia rápida.",
    ),
    # --- Plataformas cloud ---
    ProviderSpec(
        kind="bedrock",
        label="AWS Bedrock",
        category="platform",
        litellm_prefix="bedrock/",
        fields=(
            ProviderField(name="aws_region", label="Región de AWS", default="us-east-1"),
            ProviderField(
                name="aws_access_key_id",
                label="Access key ID",
                required=False,
                help="Déjalo vacío para usar el rol IAM de la máquina.",
            ),
            ProviderField(
                name="aws_secret_access_key",
                label="Secret access key",
                type="secret",
                required=False,
                help="Déjalo vacío para usar el rol IAM de la máquina.",
            ),
            ProviderField(
                name="model_id",
                label="ARN del perfil de inferencia",
                required=False,
                help="Solo para perfiles de inferencia de aplicación: indica el modelo base "
                "como modelo y aquí el ARN del perfil.",
            ),
        ),
        suggested_models=(
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "amazon.nova-pro-v1:0",
            "meta.llama3-70b-instruct-v1:0",
        ),
        docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html",
        notes="Usa perfiles de inferencia entre regiones si aplica.",
    ),
    ProviderSpec(
        kind="azure_openai",
        label="Azure OpenAI",
        category="platform",
        litellm_prefix="azure/",
        fields=(
            _api_base(None, help="Ejemplo: https://mi-recurso.openai.azure.com"),
            _api_key(),
            ProviderField(name="api_version", label="Versión de la API", default="2024-10-21"),
        ),
        docs_url="https://learn.microsoft.com/azure/ai-services/openai/",
        notes="El modelo es el nombre de tu deployment, no el del modelo base.",
    ),
    ProviderSpec(
        kind="azure_ai",
        label="Azure AI Foundry",
        category="platform",
        litellm_prefix="azure_ai/",
        fields=(_api_base(None), _api_key()),
        docs_url="https://learn.microsoft.com/azure/ai-foundry/",
        notes="Modelos del catálogo de Foundry.",
    ),
    ProviderSpec(
        kind="vertex_ai",
        label="Google Vertex AI",
        category="platform",
        litellm_prefix="vertex_ai/",
        fields=(
            ProviderField(name="vertex_project", label="Proyecto de Google Cloud"),
            ProviderField(name="vertex_location", label="Región", default="us-central1"),
            ProviderField(
                name="vertex_credentials",
                label="Credenciales de cuenta de servicio (JSON)",
                type="secret",
                help="Pega el contenido completo del JSON de la cuenta de servicio.",
            ),
        ),
        suggested_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        docs_url="https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models",
        notes="Gemini y modelos de socios en Vertex.",
    ),
    ProviderSpec(
        kind="openrouter",
        label="OpenRouter",
        category="platform",
        litellm_prefix="openrouter/",
        fields=(_api_key(),),
        suggested_models=("anthropic/claude-sonnet-5-5", "openai/gpt-4o", "deepseek/deepseek-chat"),
        docs_url="https://openrouter.ai/docs/quickstart",
        notes="Cientos de modelos con una cuenta.",
    ),
    ProviderSpec(
        kind="github_models",
        label="GitHub Models",
        category="platform",
        litellm_prefix="github/",
        fields=(
            ProviderField(
                name="api_key",
                label="Token de GitHub",
                type="secret",
                help="Token con permiso de modelos.",
            ),
        ),
        suggested_models=("gpt-4o", "Llama-3.3-70B-Instruct"),
        docs_url="https://docs.github.com/en/github-models",
        notes="No es la suscripción de Copilot (docs/spikes/github-copilot.md).",
    ),
    # --- Modelos chinos ---
    ProviderSpec(
        kind="deepseek",
        label="DeepSeek",
        category="chinese",
        litellm_prefix="deepseek/",
        fields=(
            _api_key(),
            _api_base(
                "https://api.deepseek.com",
                required=False,
                help="DeepSeek publica un único endpoint, el mismo dentro y fuera de China.",
            ),
        ),
        suggested_models=("deepseek-chat", "deepseek-reasoner"),
        docs_url="https://api-docs.deepseek.com/",
    ),
    ProviderSpec(
        kind="qwen",
        label="Qwen (Alibaba Cloud Model Studio / DashScope)",
        category="chinese",
        litellm_prefix="dashscope/",
        fields=(
            _api_key(),
            _api_base(
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                required=False,
                help=_CHINA_HELP,
                options=(
                    FieldOption(
                        value="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                        label="Internacional (Singapur)",
                    ),
                    FieldOption(
                        value="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        label="China continental (Beijing)",
                    ),
                ),
            ),
        ),
        suggested_models=("qwen-max", "qwen-plus", "qwen-turbo"),
        docs_url="https://www.alibabacloud.com/help/en/model-studio/",
    ),
    ProviderSpec(
        kind="kimi",
        label="Kimi (Moonshot AI)",
        category="chinese",
        litellm_prefix="moonshot/",
        fields=(
            _api_key(),
            _api_base(
                "https://api.moonshot.ai/v1",
                required=False,
                help=_CHINA_HELP,
                options=(
                    FieldOption(value="https://api.moonshot.ai/v1", label="Internacional"),
                    FieldOption(value="https://api.moonshot.cn/v1", label="China continental"),
                ),
            ),
        ),
        suggested_models=("kimi-k2-0905-preview", "moonshot-v1-32k"),
        docs_url="https://platform.moonshot.ai/docs",
    ),
    ProviderSpec(
        kind="glm",
        label="GLM (Z.ai / Zhipu)",
        category="chinese",
        litellm_prefix="zai/",
        fields=(
            _api_key(),
            _api_base(
                "https://api.z.ai/api/paas/v4",
                required=False,
                help=_CHINA_HELP,
                options=(
                    FieldOption(value="https://api.z.ai/api/paas/v4", label="Internacional (Z.ai)"),
                    FieldOption(
                        value="https://open.bigmodel.cn/api/paas/v4",
                        label="China continental (BigModel)",
                    ),
                ),
            ),
        ),
        suggested_models=("glm-4.6", "glm-4.5-air"),
        docs_url="https://docs.z.ai/guides/overview/quick-start",
    ),
    ProviderSpec(
        kind="minimax",
        label="MiniMax",
        category="chinese",
        litellm_prefix="minimax/",
        fields=(
            _api_key(),
            _api_base(
                "https://api.minimax.io/v1",
                required=False,
                help=_CHINA_HELP,
                options=(
                    FieldOption(value="https://api.minimax.io/v1", label="Internacional"),
                    FieldOption(value="https://api.minimaxi.com/v1", label="China continental"),
                ),
            ),
        ),
        suggested_models=("MiniMax-M2",),
        docs_url="https://platform.minimax.io/docs",
    ),
    ProviderSpec(
        kind="doubao",
        label="Doubao (ByteDance Volcengine Ark)",
        category="chinese",
        litellm_prefix="volcengine/",
        fields=(
            _api_key(),
            _api_base(
                "https://ark.cn-beijing.volces.com/api/v3",
                required=False,
                help="Ark usa el endpoint de Beijing; no hay uno internacional distinto.",
                options=(
                    FieldOption(
                        value="https://ark.cn-beijing.volces.com/api/v3",
                        label="China continental (Beijing)",
                    ),
                ),
            ),
        ),
        docs_url="https://www.volcengine.com/docs/82379",
        notes="El modelo suele ser el id del endpoint (ep-…).",
    ),
    # --- Local y compatible con OpenAI ---
    ProviderSpec(
        kind="ollama",
        label="Ollama",
        category="local",
        litellm_prefix="ollama_chat/",
        fields=(_api_base("http://localhost:11434"), _api_key(required=False)),
        suggested_models=("llama3.1", "qwen2.5"),
        docs_url="https://github.com/ollama/ollama/blob/main/docs/api.md",
    ),
    ProviderSpec(
        kind="vllm",
        label="vLLM",
        category="local",
        litellm_prefix="hosted_vllm/",
        fields=(_api_base("http://localhost:8000/v1"), _api_key(required=False)),
        docs_url="https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html",
    ),
    ProviderSpec(
        kind="lm_studio",
        label="LM Studio",
        category="local",
        litellm_prefix="lm_studio/",
        fields=(_api_base("http://localhost:1234/v1"), _api_key(required=False)),
        docs_url="https://lmstudio.ai/docs/app/api",
    ),
    ProviderSpec(
        kind="openai_compatible",
        label="Cualquier servidor compatible con OpenAI",
        category="local",
        litellm_prefix="openai/",
        fields=(_api_base(None), _api_key(required=False)),
        docs_url="https://platform.openai.com/docs/api-reference/chat",
    ),
)


def get_spec(kind: str) -> ProviderSpec | None:
    """Devuelve la entrada del catálogo para un `kind`, o `None` si no existe."""
    return next((spec for spec in CATALOG if spec.kind == kind), None)
