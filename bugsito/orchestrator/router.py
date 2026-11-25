"""
Orquestador de comandos de Bugsito.
Enruta la orden por voz hacia:
  1. Inyección de comandos en la terminal activa (wtype en Wayland / xdotool en X11)
  2. Apertura de proyectos locales en Cursor, Sublime, VS Code o terminal
  3. Control del sistema y multimedia (navegador, archivos, bloqueo, volumen)
  4. Skills personalizados definidos en `~/.config/bugsito/config.toml`
  5. Consultas conversacionales al motor Multi-LLM de Genkit (modo local por IP o por Token)
"""

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from bugsito.llm.genkit_client import GenkitLLMManager


class BugsitoOrchestrator:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.workspace_cfg = cfg.get("workspace", {})
        self.custom_skills: dict[str, dict[str, Any]] = cfg.get("skills", {}).get("custom", {})
        self.llm_manager = GenkitLLMManager(cfg)

    def _limpiar_wake_word(self, texto: str) -> str:
        wake_words = self.cfg.get("general", {}).get("wake_words", ["bugsito", "jarvis"])
        limpio = texto.strip()
        for w in wake_words:
            limpio = re.sub(rf"^(?:hola\s+|oye\s+)?{re.escape(w)}[\s,.:;!\-]*", "", limpio, flags=re.IGNORECASE)
        return limpio.strip() or texto.strip()

    def _inyectar_en_terminal(self, cmd: str) -> bool:
        """Inyecta un comando en la ventana activa (Wayland con wtype o X11 con xdotool)."""
        if subprocess.run(["which", "wtype"], capture_output=True).returncode == 0:
            try:
                subprocess.Popen(["wtype", cmd + "\n"])
                return True
            except Exception:
                pass
        if subprocess.run(["which", "xdotool"], capture_output=True).returncode == 0:
            try:
                subprocess.Popen(["xdotool", "type", "--clearmodifiers", cmd + "\n"])
                return True
            except Exception:
                pass
        return False

    def _buscar_proyecto(self, nombre_p: str) -> Path | None:
        dirs_cfg = self.workspace_cfg.get(
            "projects_dirs", ["~/Proyectos", "~/Proyectos/personal", "~/dotfiles"]
        )
        nombre_norm = nombre_p.lower().replace(" ", "-")
        nombre_raw = nombre_p.lower().replace(" ", "")

        for d_str in dirs_cfg:
            base = Path(d_str).expanduser()
            if not base.is_dir():
                continue
            if base.name.lower() == nombre_norm or nombre_norm in base.name.lower():
                return base
            try:
                for child in base.iterdir():
                    if child.is_dir():
                        cname = child.name.lower()
                        if nombre_norm in cname or nombre_raw in cname.replace("-", "").replace(".", ""):
                            return child
            except Exception:
                continue
        return None

    def procesar(self, texto_voz: str) -> str:
        """Procesa la orden transcrita y devuelve el texto que Bugsito responderá por voz."""
        texto = self._limpiar_wake_word(texto_voz)
        t_lower = texto.lower()

        # 1. Terminal / Escribir o ejecutar comandos en la terminal activa
        match_terminal = re.search(
            r"(?:escribe|corre|ejecuta)(?: en la terminal)?\s+(?:el comando\s+)?(.+)",
            t_lower,
        )
        if match_terminal and ("terminal" in t_lower or "corre" in t_lower or "ejecuta" in t_lower):
            cmd = match_terminal.group(1).strip()
            if self._inyectar_en_terminal(cmd):
                return f"Comando enviado a la terminal: {cmd}"
            return "No pude inyectar el comando a la terminal."

        # 2. Abrir proyectos en Cursor / Sublime / VS Code / Terminal
        match_proyecto = re.search(
            r"abre (?:el )?proyecto\s+([a-zA-Z0-9_\-\s]+?)(?:\s+en\s+([a-zA-Z0-9_\-]+))?$",
            t_lower,
        )
        if match_proyecto or (
            t_lower.startswith("abre ")
            and any(k in t_lower for k in ("cursor", "proyecto", "dotfiles", "context", "bugsito"))
        ):
            nombre_p = ""
            editor = self.workspace_cfg.get("default_editor", "cursor")
            terminal_bin = self.workspace_cfg.get("terminal", "kitty")

            if match_proyecto:
                nombre_p = match_proyecto.group(1).strip()
                if match_proyecto.group(2):
                    editor = match_proyecto.group(2).strip()
            elif "dotfiles" in t_lower:
                nombre_p = "dotfiles"
            elif "context" in t_lower:
                nombre_p = "context-hub"
            elif "bugsito" in t_lower:
                nombre_p = "bugsito"

            ruta_p = self._buscar_proyecto(nombre_p) if nombre_p else None
            if ruta_p and ruta_p.is_dir():
                if "sublime" in editor or "subl" in editor:
                    subprocess.Popen(["subl", str(ruta_p)])
                    return f"Abriendo {ruta_p.name} en Sublime Text."
                if "code" in editor or "vscode" in editor:
                    subprocess.Popen(["code", str(ruta_p)])
                    return f"Abriendo {ruta_p.name} en VS Code."
                if "terminal" in editor or terminal_bin in editor:
                    subprocess.Popen([terminal_bin, "--directory", str(ruta_p)])
                    return f"Abriendo terminal en {ruta_p.name}."
                subprocess.Popen([editor, str(ruta_p)])
                return f"Abriendo {ruta_p.name} en {editor.capitalize()}."

        # 3. Skills personalizados desde config.toml (ej. hermes, claude, antigravity, lazydocker)
        for trigger, info in self.custom_skills.items():
            if trigger.lower() in t_lower:
                cmd_str = info.get("cmd", "")
                resp_str = info.get("response", f"Ejecutando {trigger}.")
                if cmd_str:
                    subprocess.Popen(shlex.split(cmd_str))
                    return resp_str

        # 4. Control del Sistema y Multimedia
        terminal_cmd = self.workspace_cfg.get("terminal", "kitty")
        browser_cmd = self.workspace_cfg.get("browser", "flatpak run app.zen_browser.zen")
        fm_cmd = self.workspace_cfg.get("file_manager", "thunar")
        lock_cmd = self.workspace_cfg.get("lock_command", "hyprlock")

        if "terminal" in t_lower or "kitty" in t_lower:
            subprocess.Popen(shlex.split(terminal_cmd))
            return "Terminal abierta."
        if "navegador" in t_lower or "zen" in t_lower or "internet" in t_lower:
            subprocess.Popen(shlex.split(browser_cmd))
            return "Abriendo navegador."
        if "bloquea" in t_lower or "bloquear" in t_lower:
            subprocess.Popen(shlex.split(lock_cmd))
            return "Bloqueando pantalla."
        if "gestor de archivos" in t_lower or "archivos" in t_lower or "thunar" in t_lower:
            subprocess.Popen(shlex.split(fm_cmd))
            return "Abriendo gestor de archivos."
        if "sube" in t_lower and "volumen" in t_lower:
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"])
            return "Subiendo volumen."
        if "baja" in t_lower and "volumen" in t_lower:
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"])
            return "Bajando volumen."
        if "silencio" in t_lower or "mute" in t_lower or "mutear" in t_lower:
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
            return "Volumen alternado."

        # 5. Consulta Inteligente Multi-LLM (Genkit: modo local por IP o modo por Token)
        return self.llm_manager.generar_respuesta(texto)
