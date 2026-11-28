# chatiapp (Python)

Cliente oficial de [ChatIApp](https://github.com/jmmana/ChatIApp) para tu backend: chat, streaming SSE tipado y tokens de sesión para el chat embebido.

```bash
pip install chatiapp
```

```python
import os
from chatiapp import ChatIApp, EndUser

client = ChatIApp(base_url="https://chatiapp.tuempresa.com", api_key=os.environ["CHATIAPP_API_KEY"])
user = EndUser(id="u-123", role="gerente_sucursal", attributes={"sucursales": [1, 2]})

turn = client.chat("¿Cuánto vendí?", datasource="ventas", user=user)
if turn.needs_clarification:
    turn = client.chat("Este mes", conversation_id=turn.conversation_id, user=user)
print(turn.answer, turn.sql.sql)
```

Streaming (solo con una sesión o un token de sesión del chat embebido, **no con una API key**: el servidor responde 401; desde tu servidor usa `chat()`):

```python
browser_client = ChatIApp(base_url="https://chatiapp.tuempresa.com", api_key=session_token)
for event in browser_client.chat_stream("¿Cuánto vendí este mes?", datasource="ventas", user=user):
    if event.type == "answer.delta":
        print(event.data.text, end="")
```

Token de sesión para el widget (desde tu backend, nunca desde el navegador):

```python
session = client.create_embed_session(
    datasource="ventas", origin="https://portal.tuempresa.com", user=user
)
return {"token": session.token}
```

- `chat()` devuelve un `Turn`; `status` es `answered`, `needs_clarification`, `rejected` o `error`.
- Los errores HTTP lanzan `ChatIAppError` (`status_code`, `code`, `message`).
- Una respuesta de aclaración recuerda la fuente: el segundo `chat()` no necesita `datasource`.
- `chatiapp/_generated.py` se genera desde `docs/openapi/v1.json` (`node sdks/scripts/generate.mjs`); no lo edites.

Desarrollo: `pip install -e ".[dev]"`, `pytest`, `ruff check .`, `mypy chatiapp`.
