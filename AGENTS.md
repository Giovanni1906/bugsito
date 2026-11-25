# Contexto Unificado — `bugsito`

> **Instrucción obligatoria para todos los agentes (Cursor, Claude Code, Antigravity):**
> 1. Al comenzar cualquier tarea en este repositorio, llama **primero** a la herramienta MCP `get_project_context(project_name="bugsito")` del servidor `context-hub` si está disponible.
> 2. Mantén la compatibilidad dual de **Bugsito**:
>    - **Integración nativa con `~/dotfiles`**: lectura dinámica de `~/dotfiles/tema/tema.conf`, síntesis de voz delegada a `~/dotfiles/utils/voz.sh` y deducción de IP desde `~/dotfiles/.env`.
>    - **Operación autónoma en otras PCs**: fallbacks en `~/.config/bugsito/config.toml`, motor Piper/espeak-ng integrado y ventana flotante si no existe `GtkLayerShell`.
> 3. Toda configuración de LLMs (modo local por IP o modo por Token) pasa por el gestor de **Genkit** (`bugsito/llm/genkit_client.py` y `genkit/src/index.ts`). Nunca quemar IPs privadas ni API keys en el código fuente.
