"""
Gestión de configuración, secretos (.env) y temas visuales para Bugsito.
Permite que Bugsito se integre de forma nativa con ~/dotfiles (tema.conf, voz.sh, .env)
y que funcione de manera 100% autónoma en cualquier otra distribución o PC.
"""

import os
import re
import tomllib
from pathlib import Path
from typing import Any

USER = os.environ.get("USER", "nova")
HOME = Path.home()
REPO_ROOT = Path(__file__).resolve().parent.parent
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")))
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", str(HOME / ".local/share")))

CONFIG_DIR = XDG_CONFIG_HOME / "bugsito"
USER_CONFIG_FILE = CONFIG_DIR / "config.toml"
USER_ENV_FILE = CONFIG_DIR / ".env"
DOTFILES_ENV_FILE = HOME / "dotfiles/.env"
EXAMPLE_CONFIG_FILE = REPO_ROOT / "config.example.toml"

PIDFILE = Path(f"/tmp/bugsito_{USER}.pid")
STOPFILE = Path(f"/tmp/bugsito_{USER}.stop")
AUDIO_FILE = Path(f"/tmp/bugsito_audio_{USER}.wav")


def cargar_variables_entorno() -> None:
    """
    Carga variables desde ~/.config/bugsito/.env, repo/.env y ~/dotfiles/.env
    sin sobrescribir las variables ya exportadas en la sesión actual.
    """
    candidatos = [USER_ENV_FILE, REPO_ROOT / ".env", DOTFILES_ENV_FILE]
    for env_path in candidatos:
        if not env_path.is_file():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    if k and k not in os.environ and v:
                        os.environ[k] = v
        except Exception:
            pass


def deducir_host_ollama_desde_entorno() -> str:
    """
    Deduce la IP o URL del servidor Ollama local/Tailscale:
    1. BUGSITO_OLLAMA_HOST explícito
    2. IP extraída de CONTEXT_HUB_URL (en ~/dotfiles/.env) en el puerto 11434
    3. Fallback a http://127.0.0.1:11434
    """
    explicit = os.environ.get("BUGSITO_OLLAMA_HOST", "").strip()
    if explicit:
        return explicit.rstrip("/")

    context_url = os.environ.get("CONTEXT_HUB_URL", "").strip()
    if context_url and "ip_tailscale" not in context_url and "<IP_" not in context_url:
        match = re.match(r"^https?://([^:/]+)", context_url)
        if match:
            ip = match.group(1)
            return f"http://{ip}:11434"

    return "http://127.0.0.1:11434"


def cargar_config() -> dict[str, Any]:
    """Lee ~/.config/bugsito/config.toml o usa config.example.toml como respaldo."""
    cargar_variables_entorno()

    cfg: dict[str, Any] = {}
    if EXAMPLE_CONFIG_FILE.is_file():
        try:
            cfg = tomllib.loads(EXAMPLE_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    if USER_CONFIG_FILE.is_file():
        try:
            user_cfg = tomllib.loads(USER_CONFIG_FILE.read_text(encoding="utf-8"))
            _deep_merge(cfg, user_cfg)
        except Exception:
            pass

    return cfg


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def hex_a_rgb_float(hex_color: str, fallback: str = "#a77bf3") -> tuple[float, float, float]:
    """Convierte un color '#RRGGBB' a tupla (r, g, b) en rango 0.0 - 1.0."""
    val = hex_color.strip().strip("\"'")
    if not (val.startswith("#") and len(val) == 7):
        val = fallback
    try:
        r = int(val[1:3], 16) / 255.0
        g = int(val[3:5], 16) / 255.0
        b = int(val[5:7], 16) / 255.0
        return (r, g, b)
    except Exception:
        return (0.65, 0.48, 0.95)


def leer_colores_tema(cfg: dict[str, Any]) -> dict[str, tuple[float, float, float]]:
    """
    Lee los colores del tema activo:
    - Si existe el archivo configurado en `theme.env_file` (ej. ~/dotfiles/tema/tema.conf),
      extrae ACENTO, SECUNDARIO e INFO en tiempo real.
    - Si no existe (otra PC sin dotfiles), usa los valores hexadecimales de `config.toml`.
    """
    theme_cfg = cfg.get("theme", {})
    env_file_str = theme_cfg.get("env_file", "~/dotfiles/tema/tema.conf")
    env_file = Path(env_file_str).expanduser()

    raw_colors = {
        "ACENTO": theme_cfg.get("accent", "#a77bf3"),
        "SECUNDARIO": theme_cfg.get("secondary", "#7ee08f"),
        "INFO": theme_cfg.get("info", "#8fd3f4"),
    }

    if env_file.is_file():
        try:
            for linea in env_file.read_text(encoding="utf-8").splitlines():
                linea = linea.strip()
                for clave in ("ACENTO", "SECUNDARIO", "INFO"):
                    if linea.startswith(f"{clave}="):
                        val = linea.split("=", 1)[1].strip().strip("\"'")
                        if val.startswith("#") and len(val) == 7:
                            raw_colors[clave] = val
        except Exception:
            pass

    return {
        "accent": hex_a_rgb_float(raw_colors["ACENTO"], "#a77bf3"),
        "secondary": hex_a_rgb_float(raw_colors["SECUNDARIO"], "#7ee08f"),
        "info": hex_a_rgb_float(raw_colors["INFO"], "#8fd3f4"),
    }


def actualizar_clave_llm_config(clave: str, nuevo_valor: str) -> Path:
    """Actualiza `mode` o `active_profile` dentro de ~/.config/bugsito/config.toml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not USER_CONFIG_FILE.is_file() and EXAMPLE_CONFIG_FILE.is_file():
        USER_CONFIG_FILE.write_text(EXAMPLE_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    texto = USER_CONFIG_FILE.read_text(encoding="utf-8")
    patron = re.compile(rf"^(\s*{re.escape(clave)}\s*=\s*)\"[^\"]*\"", re.MULTILINE)
    if patron.search(texto):
        texto = patron.sub(rf'\1"{nuevo_valor}"', texto, count=1)
    else:
        texto += f'\n[llm]\n{clave} = "{nuevo_valor}"\n'

    USER_CONFIG_FILE.write_text(texto, encoding="utf-8")
    return USER_CONFIG_FILE
