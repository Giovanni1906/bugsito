"""
Captura de micrófono y transcripción local (Speech-to-Text) con whisper.cpp.
Funciona tanto en NixOS (/nix/store/*-whisper-cpp-*/bin/whisper-cli) como en cualquier distro Linux.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from bugsito.config import AUDIO_FILE


def buscar_whisper_cli() -> str:
    """Encuentra el ejecutable whisper-cli (o whisper-cpp) en PATH o en /nix/store."""
    for bin_name in ("whisper-cli", "whisper-cpp", "main"):
        res = subprocess.run(["which", bin_name], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()

    nix_store = Path("/nix/store")
    if nix_store.is_dir():
        candidatos = list(nix_store.glob("*-whisper-cpp-*/bin/whisper-cli"))
        if candidatos:
            return str(candidatos[0])

    return "whisper-cli"


def asegurar_modelo_whisper(audio_cfg: dict[str, Any]) -> Path:
    """Descarga el modelo ggml-base.bin si aún no existe en ~/.local/share/whisper."""
    whisper_dir = Path(audio_cfg.get("whisper_model_dir", "~/.local/share/whisper")).expanduser()
    model_name = audio_cfg.get("whisper_model_name", "ggml-base.bin")
    model_url = audio_cfg.get(
        "whisper_model_url",
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
    )
    model_path = whisper_dir / model_name

    if not model_path.is_file():
        whisper_dir.mkdir(parents=True, exist_ok=True)
        tmp = model_path.with_suffix(".tmp")
        try:
            subprocess.run(
                ["curl", "-sSL", "-o", str(tmp), model_url],
                check=True,
                timeout=90,
            )
            tmp.rename(model_path)
        except Exception as e:
            if tmp.exists():
                tmp.unlink()
            print(f"[Bugsito STT] Error descargando modelo Whisper: {e}", file=sys.stderr)

    return model_path


def iniciar_grabacion_ffmpeg() -> subprocess.Popen | None:
    """Inicia la captura de micrófono a 16kHz mono con ffmpeg (PulseAudio/PipeWire o ALSA)."""
    if AUDIO_FILE.exists():
        try:
            AUDIO_FILE.unlink()
        except Exception:
            pass

    for backend in ("pulse", "alsa"):
        try:
            proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "quiet",
                    "-f",
                    backend,
                    "-i",
                    "default",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(AUDIO_FILE),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return proc
        except Exception:
            continue

    print("[Bugsito STT] No se pudo iniciar ffmpeg para grabar audio.", file=sys.stderr)
    return None


def transcribir_audio(cfg: dict[str, Any]) -> str:
    """Transcribe el archivo WAV grabado usando whisper-cli local."""
    if not AUDIO_FILE.is_file() or AUDIO_FILE.stat().st_size < 1000:
        return ""

    audio_cfg = cfg.get("audio", {})
    lang = cfg.get("general", {}).get("language", "es")
    prompt_contexto = audio_cfg.get(
        "whisper_prompt",
        "Bugsito, Jarvis, Hermes, terminal, proyecto, git, dotfiles, código, abre, ejecuta, corre, cursor",
    )

    whisper_bin = buscar_whisper_cli()
    model_path = asegurar_modelo_whisper(audio_cfg)

    texto_transcrito = ""
    try:
        res = subprocess.run(
            [
                whisper_bin,
                "-m",
                str(model_path),
                "-f",
                str(AUDIO_FILE),
                "-l",
                lang,
                "--no-timestamps",
                "-nt",
                "--prompt",
                prompt_contexto,
            ],
            capture_output=True,
            text=True,
            timeout=14,
        )
        lineas = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        texto_transcrito = " ".join(lineas)
    except Exception as e:
        print(f"[Bugsito STT] Error en Whisper: {e}", file=sys.stderr)

    # Limpiar etiquetas de ruido de Whisper como [Música], (risas), etc.
    texto_limpio = re.sub(r"\[.*?\]|\(.*?\)", "", texto_transcrito).strip()
    return texto_limpio
