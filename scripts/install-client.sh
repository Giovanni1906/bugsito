#!/usr/bin/env bash
# =============================================================================
# INSTALADOR DE CLIENTE Y COMANDOS CLI — BUGSITO (antes Jarvis)
# =============================================================================
# Instala en cualquier PC o distribución Linux (NixOS, Ubuntu, Arch, Fedora):
#   - Comandos globales en ~/.local/bin: `bugsito` y `jarvis` (alias compatible)
#   - Configuración base en ~/.config/bugsito/config.toml (si no está ya enlazada por dotfiles)
#   - Archivo de secretos/LLMs en ~/.config/bugsito/.env (chmod 600)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_SCRIPT="$REPO_DIR/bugsito.sh"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/bugsito"
USER_CONFIG_FILE="$CONFIG_DIR/config.toml"
USER_ENV_FILE="$CONFIG_DIR/.env"

NON_INTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --non-interactive|-y) NON_INTERACTIVE=1 ;;
    esac
done

ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
aviso() { printf '  \033[33m!\033[0m %s\n' "$*"; }

printf '\033[1;36m==> Instalando Bugsito (asistente de voz y motor Genkit Multi-LLM)\033[0m\n'

chmod +x "$CLI_SCRIPT"
mkdir -p "$BIN_DIR" "$CONFIG_DIR"

# 1. Crear enlaces simbólicos en ~/.local/bin (bugsito y alias jarvis por compatibilidad)
ln -sf "$CLI_SCRIPT" "$BIN_DIR/bugsito"
ln -sf "$CLI_SCRIPT" "$BIN_DIR/jarvis"
ok "Comandos enlazados en $BIN_DIR/bugsito y $BIN_DIR/jarvis"

# 2. Asegurar ~/.local/bin en PATH
if [ -f "$HOME/.bashrc" ] && ! grep -q '\.local/bin' "$HOME/.bashrc" 2>/dev/null; then
    printf '\n# Bugsito CLI\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
    ok "Añadido ~/.local/bin al PATH en ~/.bashrc"
fi

# 3. Crear ~/.config/bugsito/config.toml si no existe (ni es symlink de dotfiles)
if [ ! -e "$USER_CONFIG_FILE" ] && [ -f "$REPO_DIR/config.example.toml" ]; then
    cp "$REPO_DIR/config.example.toml" "$USER_CONFIG_FILE"
    ok "Creado archivo de configuración en $USER_CONFIG_FILE"
fi

# 4. Crear ~/.config/bugsito/.env (permisos 600) deduciendo IP de dotfiles/.env si existe
if [ ! -f "$USER_ENV_FILE" ]; then
    OLLAMA_HOST_DEFAULT="http://127.0.0.1:11434"
    if [ -f "$HOME/dotfiles/.env" ]; then
        ch_url="$(grep -E '^(export )?CONTEXT_HUB_URL=' "$HOME/dotfiles/.env" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
        if [ -n "$ch_url" ] && [[ "$ch_url" != *"ip_tailscale"* ]]; then
            mac_ip="$(echo "$ch_url" | sed -E 's|https?://([^:/]+).*|\1|')"
            [ -n "$mac_ip" ] && OLLAMA_HOST_DEFAULT="http://${mac_ip}:11434"
        fi
    fi

    cat > "$USER_ENV_FILE" <<EOF
# Configuración de LLMs y Tokens de Bugsito (Genkit)
# Modo: "local" (por IP/Tailscale), "token" (API Key Cloud) o "auto" (fallback automático)
export BUGSITO_LLM_MODE="auto"
export BUGSITO_LLM_PROFILE="mac-ollama"
export BUGSITO_OLLAMA_HOST="${OLLAMA_HOST_DEFAULT}"
export BUGSITO_OLLAMA_MODEL="llama3.1:8b"

# Tokens para modo Cloud con Genkit (completa los que utilices)
export GEMINI_API_KEY=""
export OPENAI_API_KEY=""
export GROQ_API_KEY=""
export DEEPSEEK_API_KEY=""
export ANTHROPIC_API_KEY=""
EOF
    chmod 600 "$USER_ENV_FILE"
    ok "Creado archivo de secretos LLM en $USER_ENV_FILE (permisos 600)"
fi

printf '\n  \033[1;32m¡Bugsito listo!\033[0m Comandos útiles:\n'
printf '    • \033[1mbugsito\033[0m                  (abre/detiene la bola de energía; atajo SUPER + SPACE)\n'
printf '    • \033[1mbugsito llm list\033[0m         (ver perfiles LLM en modo local por IP o por Token)\n'
printf '    • \033[1mbugsito llm mode <modo>\033[0m  (cambiar entre local, token o auto)\n'
printf '    • \033[1mbugsito llm use <perfil>\033[0m (elegir mac-ollama, local-ollama, gemini, openai, groq...)\n'
printf '    • \033[1mbugsito doctor\033[0m           (diagnosticar audio, tema de dotfiles y LLMs)\n'
