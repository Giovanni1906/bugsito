"""
Síntesis de Voz (Text-to-Speech) para Bugsito.
- Si está integrado con `~/dotfiles` (`external_tts_cmd = "~/dotfiles/utils/voz.sh --silencio"`),
  reutiliza `voz.sh` para mantener exactamente la misma voz del ecosistema.
- Si corre en otra PC de forma independiente, usa directamente `piper` (descargando el modelo
  neuronal en español si falta) o `espeak-ng` como respaldo universal.
"""

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def _buscar_piper() -> str | None:
    res = subprocess.run(["which", "piper"], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    nix_store = Path("/nix/store")
    if nix_store.is_dir():
        for cand in nix_store.glob("*-piper-*/bin/piper"):
            if cand.is_file():
                return str(cand)
    return None


def _asegurar_modelo_piper(piper_dir: Path, voice_name: str) -> Path | None:
    onnx_path = piper_dir / f"{voice_name}.onnx"
    json_path = piper_dir / f"{voice_name}.onnx.json"
    if onnx_path.is_file() and json_path.is_file():
        return onnx_path

    base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_MX/claude/high"
    try:
        piper_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["curl", "-sSL", "-o", str(onnx_path), f"{base_url}/{voice_name}.onnx"],
            check=True,
            timeout=60,
        )
        subprocess.run(
            ["curl", "-sSL", "-o", str(json_path), f"{base_url}/{voice_name}.onnx.json"],
            check=True,
            timeout=30,
        )
        return onnx_path
    except Exception:
        return None


def hablar(texto: str, cfg: dict[str, Any]) -> None:
    """Reproduce por altavoces la respuesta de Bugsito."""
    if not texto:
        return

    audio_cfg = cfg.get("audio", {})
    ext_cmd_str = str(audio_cfg.get("external_tts_cmd", "~/dotfiles/utils/voz.sh --silencio")).strip()

    # 1. Intentar script externo del ecosistema dotfiles (ej. ~/dotfiles/utils/voz.sh)
    if ext_cmd_str:
        partes = shlex.split(ext_cmd_str)
        if partes:
            bin_path = Path(partes[0]).expanduser()
            if bin_path.is_file():
                try:
                    subprocess.run([str(bin_path), *partes[1:], texto], timeout=18)
                    return
                except Exception as e:
                    print(f"[Bugsito TTS] Error en TTS externo ({bin_path}): {e}", file=sys.stderr)

    # 2. Motor Piper TTS integrado (para otras PCs sin dotfiles)
    piper_bin = _buscar_piper()
    if piper_bin:
        piper_dir = Path(audio_cfg.get("piper_model_dir", "~/.local/share/piper")).expanduser()
        voice_name = audio_cfg.get("piper_default_voice", "es_MX-claude-high")
        modelo = _asegurar_modelo_piper(piper_dir, voice_name)
        if modelo and modelo.is_file():
            try:
                p_piper = subprocess.Popen(
                    [piper_bin, "--model", str(modelo), "--output-raw"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                raw_audio, _ = p_piper.communicate(input=texto.encode("utf-8"), timeout=12)
                if raw_audio:
                    for player_cmd in (
                        ["paplay", "--raw", "--rate=22050", "--channels=1", "--format=s16le"],
                        ["aplay", "-r", "22050", "-c", "1", "-f", "S16_LE", "-t", "raw", "-q"],
                    ):
                        if subprocess.run(["which", player_cmd[0]], capture_output=True).returncode == 0:
                            p_play = subprocess.Popen(
                                player_cmd,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            p_play.communicate(input=raw_audio, timeout=15)
                            return
            except Exception:
                pass

    # 3. Respaldo universal: espeak-ng
    espeak_voice = audio_cfg.get("espeak_voice", "es-419")
    try:
        subprocess.run(
            ["espeak-ng", "-v", espeak_voice, "-s", "145", "-a", "90", "--", texto],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception:
        pass
