#!/usr/bin/env python3
"""
CLI Principal de Bugsito (antes Jarvis).
Comandos disponibles:
  bugsito [toggle]              Activa la bola de energía o finaliza la escucha si ya está abierta
  bugsito ask "<texto>"         Envía una orden en texto al orquestador/Genkit y opcionalmente la habla (--speak)
  bugsito llm list              Lista los perfiles de LLM configurados (modo local por IP y modo por Token)
  bugsito llm mode <modo>       Cambia el modo de LLM: local | token | auto
  bugsito llm use <perfil>      Cambia el perfil de LLM activo (ej. mac-ollama, local-ollama, gemini, openai, groq)
  bugsito llm test [perfil]     Prueba la conexión con el perfil de LLM activo o el indicado
  bugsito genkit-serve          Inicia el servidor local de flujos Firebase Genkit (puerto 3400)
  bugsito genkit-ui             Abre la interfaz de desarrollo Firebase Genkit UI
  bugsito doctor                Verifica dependencias (GTKLayerShell, whisper-cli, ffmpeg, TTS, LLMs)
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

from bugsito.audio.stt import buscar_whisper_cli
from bugsito.audio.tts import hablar
from bugsito.config import (
    PIDFILE,
    REPO_ROOT,
    STOPFILE,
    USER_CONFIG_FILE,
    USER_ENV_FILE,
    actualizar_clave_llm_config,
    cargar_config,
)
from bugsito.llm.genkit_client import GenkitLLMManager
from bugsito.orchestrator.router import BugsitoOrchestrator


def cmd_toggle() -> int:
    """Si Bugsito ya está grabando, le envía señal de parada; si no, abre el widget."""
    if PIDFILE.is_file():
        try:
            pid = int(PIDFILE.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            STOPFILE.touch()
            os.kill(pid, signal.SIGUSR1)
            return 0
        except Exception:
            for f in (PIDFILE, STOPFILE):
                if f.exists():
                    try:
                        f.unlink()
                    except Exception:
                        pass

    from bugsito.ui.orb import lanzar_ui

    lanzar_ui()
    return 0


def cmd_ask(args: list[str]) -> int:
    speak = False
    filtrados: list[str] = []
    for a in args:
        if a in ("--speak", "-s", "--voz"):
            speak = True
        else:
            filtrados.append(a)

    texto = " ".join(filtrados).strip()
    if not texto:
        print("Uso: bugsito ask [--speak] \"<tu consulta u orden>\"", file=sys.stderr)
        return 1

    cfg = cargar_config()
    orch = BugsitoOrchestrator(cfg)
    respuesta = orch.procesar(texto)
    print(respuesta)
    if speak:
        hablar(respuesta, cfg)
    return 0


def cmd_llm(args: list[str]) -> int:
    cfg = cargar_config()
    mgr = GenkitLLMManager(cfg)
    sub = args[0] if args else "list"

    if sub == "list":
        print(f"Modo global LLM (Genkit): \033[1;36m{mgr.mode}\033[0m")
        print(f"Perfil activo:            \033[1;32m{mgr.active_profile}\033[0m\n")
        print(f"{'PERFIL':<16} {'MODO':<8} {'PROVEEDOR':<18} {'MODELO':<24} {'ESTADO / ENDPOINT'}")
        print("-" * 92)
        for p in mgr.estado_perfiles():
            mark = "● " if p["active"] else "  "
            status = "✓ Configurado" if p["configured"] else "✗ Falta Token (.env)"
            print(
                f"{mark}{p['name']:<14} {p['type']:<8} {p['provider']:<18} "
                f"{p['model']:<24} {status} ({p['endpoint']})"
            )
        return 0

    if sub == "mode":
        if len(args) < 2 or args[1] not in ("local", "token", "auto"):
            print("Uso: bugsito llm mode <local|token|auto>", file=sys.stderr)
            return 1
        nuevo_modo = args[1]
        ruta = actualizar_clave_llm_config("mode", nuevo_modo)
        print(f"✓ Modo de LLM actualizado a '{nuevo_modo}' en {ruta}")
        return 0

    if sub in ("use", "set"):
        if len(args) < 2:
            print("Uso: bugsito llm use <nombre-perfil>", file=sys.stderr)
            return 1
        perfil = args[1]
        if perfil not in mgr.profiles:
            print(
                f"✗ El perfil '{perfil}' no existe en config.toml. Perfiles disponibles: {', '.join(mgr.profiles)}",
                file=sys.stderr,
            )
            return 1
        ruta = actualizar_clave_llm_config("active_profile", perfil)
        print(f"✓ Perfil de LLM activo cambiado a '{perfil}' en {ruta}")
        return 0

    if sub == "test":
        perfil = args[1] if len(args) >= 2 else mgr.active_profile
        if perfil not in mgr.profiles:
            print(f"✗ Perfil '{perfil}' no encontrado.", file=sys.stderr)
            return 1
        prof_data = mgr.profiles[perfil]
        print(
            f"Probando perfil '{perfil}' (modo={prof_data.get('type')}, "
            f"proveedor={prof_data.get('provider')}, modelo={prof_data.get('model')})..."
        )
        try:
            resp = mgr.consultar_perfil("Hola Bugsito, responde con un saludo corto.", perfil, prof_data)
            print(f"\033[32m✓ Respuesta exitosa:\033[0m {resp}")
            return 0
        except Exception as e:
            print(f"\033[31m✗ Error conectando con '{perfil}':\033[0m {e}", file=sys.stderr)
            return 1

    print("Subcomandos de llm: list | mode <local|token|auto> | use <perfil> | test [perfil]")
    return 1


def cmd_genkit(ui: bool = False) -> int:
    genkit_dir = REPO_ROOT / "genkit"
    if not genkit_dir.is_dir():
        print(f"✗ No se encontró el directorio Genkit en {genkit_dir}", file=sys.stderr)
        return 1

    if not (genkit_dir / "node_modules").is_dir():
        print("==> Instalando dependencias de Firebase Genkit (npm install)...")
        subprocess.run(["npm", "install"], cwd=str(genkit_dir), check=True)

    script_name = "genkit:ui" if ui else "serve"
    return subprocess.call(["npm", "run", script_name], cwd=str(genkit_dir))


def cmd_doctor() -> int:
    cfg = cargar_config()
    mgr = GenkitLLMManager(cfg)
    print("\033[1;36m==> Diagnóstico de Bugsito (Doctor)\033[0m")
    print(f"  • Archivo config:  {USER_CONFIG_FILE} ({'existe' if USER_CONFIG_FILE.is_file() else 'usando defaults'})")
    print(f"  • Archivo .env:    {USER_ENV_FILE} ({'existe' if USER_ENV_FILE.is_file() else 'no creado aún'})")
    tema_path = Path(cfg.get("theme", {}).get("env_file", "~/dotfiles/tema/tema.conf")).expanduser()
    print(f"  • Tema dotfiles:   {tema_path} ({'conectado ✓' if tema_path.is_file() else 'modo autónomo'})")
    whisper_bin = buscar_whisper_cli()
    w_ok = subprocess.run(["which", whisper_bin], capture_output=True).returncode == 0 or Path(whisper_bin).is_file()
    print(f"  • STT whisper-cli: {whisper_bin} ({'disponible ✓' if w_ok else 'no encontrado ✗'})")
    ff_ok = subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0
    print(f"  • Captura ffmpeg:  {'disponible ✓' if ff_ok else 'no encontrado ✗'}")
    print(f"  • Modo LLM Genkit: {mgr.mode} (perfil activo: {mgr.active_profile})")
    return 0


def ayuda() -> None:
    print(__doc__.strip())


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("toggle", "ui", "orb"):
        return cmd_toggle()
    cmd = args[0]
    if cmd in ("-h", "--help", "help"):
        ayuda()
        return 0
    if cmd == "ask":
        return cmd_ask(args[1:])
    if cmd == "llm":
        return cmd_llm(args[1:])
    if cmd == "genkit-serve":
        return cmd_genkit(ui=False)
    if cmd == "genkit-ui":
        return cmd_genkit(ui=True)
    if cmd == "doctor":
        return cmd_doctor()

    ayuda()
    return 1


if __name__ == "__main__":
    sys.exit(main())
