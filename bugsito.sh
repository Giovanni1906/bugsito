#!/usr/bin/env bash
# =============================================================================
# Bugsito (antes Jarvis) — Lanzador y CLI del Asistente de Voz
# =============================================================================
# - Sin argumentos o `toggle`: activa/detiene el widget de bola de energía (SUPER + SPACE).
# - Con subcomandos (`ask`, `llm`, `genkit-serve`, `genkit-ui`, `doctor`, `--help`):
#   se ejecuta de forma interactiva en la terminal.

set -euo pipefail

# Resolver ruta real del repositorio aunque se invoque mediante symlink en ~/.local/bin
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
REPO_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

export PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}"

PIDFILE="/tmp/bugsito_${USER:-nova}.pid"
STOPFILE="/tmp/bugsito_${USER:-nova}.stop"
LOG="/tmp/bugsito_${USER:-nova}.log"

resolver_python_gtk() {
    # En NixOS: aprovecha el entorno Python + GTK3 + GtkLayerShell del sistema (bugsito-env o calendario)
    local ref_bin python_gtk
    for cand in bugsito-gtk calendario multimedia; do
        ref_bin=$(command -v "$cand" 2>/dev/null || true)
        if [[ -n "$ref_bin" && -f "$ref_bin" ]]; then
            eval "$(grep '^export ' "$ref_bin" 2>/dev/null || true)"
            python_gtk=$(awk '/^exec / { print $2 }' "$ref_bin" | head -n1)
            if [[ -n "$python_gtk" && -x "$python_gtk" ]]; then
                printf '%s' "$python_gtk"
                return 0
            fi
        fi
    done
    command -v python3
}

CMD="${1:-toggle}"

# Subcomandos interactivos de terminal (no abren la UI en segundo plano)
case "$CMD" in
    ask|llm|genkit-serve|genkit-ui|doctor|-h|--help|help)
        PY_BIN="$(resolver_python_gtk)"
        exec "$PY_BIN" -m bugsito.cli "$@"
        ;;
esac

# Modo Toggle de Interfaz Gráfica (SUPER + SPACE)
if [[ -f "$PIDFILE" ]]; then
    pid=$(<"$PIDFILE")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        touch "$STOPFILE"
        kill -USR1 "$pid" 2>/dev/null || true
        exit 0
    fi
    rm -f "$PIDFILE" "$STOPFILE"
fi

ejecutar_ui() {
    local py_bin
    py_bin="$(resolver_python_gtk)"
    exec "$py_bin" -m bugsito.cli toggle
}

ejecutar_ui >"$LOG" 2>&1 &
echo $! >"$PIDFILE"
disown
