"""
Cliente y Orquestador Multi-LLM gestionado con Genkit para Bugsito.
Soporta dos modos principales de operación:
  1. Modo Local por IP (`mode = "local"`):
     Conecta con servidores en la red local o Tailscale (Ollama en Mac Mini / localhost,
     vLLM, LM Studio, llama.cpp).
  2. Modo por Token (`mode = "token"`):
     Conecta mediante API Key / Token a modelos en la nube a través de Genkit
     (Google Gemini, OpenAI, Groq, DeepSeek, Anthropic).
  3. Modo Automático (`mode = "auto"`):
     Intenta primero el perfil activo (y/o el servidor de flujos Genkit local) y,
     si no está disponible, recorre la lista de fallback configurada.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from bugsito.config import deducir_host_ollama_desde_entorno


class GenkitLLMManager:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.llm_cfg = cfg.get("llm", {})
        self.profiles: dict[str, dict[str, Any]] = self.llm_cfg.get("profiles", {})

        # Priorizar variables de entorno si están definidas
        self.mode = os.environ.get("BUGSITO_LLM_MODE", self.llm_cfg.get("mode", "auto")).lower()
        self.active_profile = os.environ.get(
            "BUGSITO_LLM_PROFILE", self.llm_cfg.get("active_profile", "mac-ollama")
        )
        self.fallback_order: list[str] = self.llm_cfg.get(
            "fallback_order", ["mac-ollama", "gemini", "openai", "groq", "local-ollama"]
        )
        self.use_genkit_server: bool = bool(self.llm_cfg.get("use_genkit_server", True))
        self.genkit_server_url: str = os.environ.get(
            "BUGSITO_GENKIT_URL", self.llm_cfg.get("genkit_server_url", "http://127.0.0.1:3400")
        ).rstrip("/")
        self.system_prompt: str = self.llm_cfg.get(
            "system_prompt",
            (
                "Eres Bugsito, el asistente de voz inteligente del sistema NixOS. "
                "Responde siempre en español de forma natural, concisa y directa (máximo 1 o 2 oraciones breves). "
                "Sin texto de relleno, sin markdown ni listas, optimizado para ser leído por voz."
            ),
        )

    def _orden_perfiles_candidatos(self) -> list[tuple[str, dict[str, Any]]]:
        """Devuelve la lista ordenada de perfiles a intentar según `mode` (`local`, `token`, `auto`)."""
        orden_nombres: list[str] = []
        if self.active_profile in self.profiles:
            orden_nombres.append(self.active_profile)
        for name in self.fallback_order:
            if name in self.profiles and name not in orden_nombres:
                orden_nombres.append(name)
        for name in self.profiles:
            if name not in orden_nombres:
                orden_nombres.append(name)

        candidatos: list[tuple[str, dict[str, Any]]] = []
        for name in orden_nombres:
            prof = self.profiles[name]
            ptype = prof.get("type", "local").lower()
            if self.mode == "local" and ptype != "local":
                continue
            if self.mode == "token" and ptype != "token":
                continue
            candidatos.append((name, prof))
        return candidatos

    def resolver_host_local(self, profile: dict[str, Any]) -> str:
        """Resuelve la URL completa (http://IP:PUERTO) para un perfil en modo local."""
        host = str(profile.get("host", "auto")).strip()
        port = profile.get("port", 11434)
        if host == "auto" or not host:
            base = deducir_host_ollama_desde_entorno()
            return base
        host = host.rstrip("/")
        if not host.startswith("http://") and not host.startswith("https://"):
            host = f"http://{host}"
        # Añadir puerto si no viene incluido en el host
        sin_proto = host.split("://", 1)[1]
        if ":" not in sin_proto and port:
            return f"{host}:{port}"
        return host

    def resolver_token(self, profile: dict[str, Any]) -> str:
        """Obtiene el token/API key desde la variable de entorno configurada o desde el perfil."""
        direct = str(profile.get("api_key", "")).strip()
        if direct:
            return direct
        env_name = str(profile.get("api_key_env", "")).strip()
        if env_name:
            return os.environ.get(env_name, "").strip()
        return os.environ.get("BUGSITO_API_KEY", "").strip()

    def _consultar_via_genkit_server(
        self, prompt: str, profile_name: str, profile: dict[str, Any]
    ) -> str | None:
        """
        Si el servidor local de flujos Genkit (`bugsito genkit-serve`) está corriendo,
        ejecuta el flujo `bugsitoVoiceFlow` a través de Genkit.
        """
        if not self.use_genkit_server:
            return None

        ptype = profile.get("type", "local")
        provider = profile.get("provider", "ollama")
        model = profile.get("model", "llama3.1:8b")
        timeout = float(profile.get("timeout", 8))

        payload_data: dict[str, Any] = {
            "prompt": prompt,
            "systemPrompt": self.system_prompt,
            "mode": ptype if ptype in ("local", "token") else "auto",
            "provider": provider,
            "model": model,
        }

        if ptype == "local":
            payload_data["host"] = self.resolver_host_local(profile)
            if profile.get("base_url"):
                payload_data["baseUrl"] = profile["base_url"]
        else:
            api_key = self.resolver_token(profile)
            if not api_key:
                return None
            payload_data["apiKey"] = api_key
            if profile.get("base_url"):
                payload_data["baseUrl"] = profile["base_url"]

        req = urllib.request.Request(
            f"{self.genkit_server_url}/bugsitoVoiceFlow",
            data=json.dumps(payload_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                texto = str(data.get("response", "")).strip()
                if texto:
                    return texto
        except Exception:
            return None
        return None

    def consultar_perfil(self, prompt: str, profile_name: str, profile: dict[str, Any]) -> str:
        """
        Ejecuta la consulta contra un perfil específico (Local por IP o Cloud por Token).
        Primero intenta el servidor de flujos Genkit si está activo; si no, usa el adaptador directo.
        """
        # 1. Intentar servidor de flujos Genkit local si está levantado
        via_genkit = self._consultar_via_genkit_server(prompt, profile_name, profile)
        if via_genkit:
            return via_genkit

        ptype = profile.get("type", "local").lower()
        provider = profile.get("provider", "ollama").lower()
        model = profile.get("model", "llama3.1:8b")
        timeout = float(profile.get("timeout", 8))

        # 2. MODO LOCAL POR IP (Ollama o servidor OpenAI-compatible en LAN/Tailscale)
        if ptype == "local" or provider == "ollama":
            host_url = self.resolver_host_local(profile)
            if provider == "ollama":
                full_prompt = f'{self.system_prompt}\n\nEl usuario te ha dicho por voz: "{prompt}"'
                payload = json.dumps(
                    {
                        "model": model,
                        "prompt": full_prompt,
                        "stream": False,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    f"{host_url}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    res_text = str(data.get("response", "")).strip()
                    if res_text:
                        return res_text
                    raise RuntimeError(f"Respuesta vacía desde Ollama ({host_url})")
            else:
                # Servidor local OpenAI-compatible (LM Studio, vLLM, llama.cpp) por IP
                base_url = str(profile.get("base_url", f"{host_url}/v1")).rstrip("/")
                return self._consultar_openai_compatible(
                    prompt=prompt,
                    base_url=base_url,
                    model=model,
                    api_key=self.resolver_token(profile),
                    timeout=timeout,
                )

        # 3. MODO POR TOKEN (Gemini, OpenAI, Groq, DeepSeek, Anthropic)
        api_key = self.resolver_token(profile)
        if not api_key:
            raise ValueError(
                f"El perfil '{profile_name}' requiere token ({profile.get('api_key_env', 'API_KEY')})"
            )

        if provider == "googleai":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            full_prompt = f'{self.system_prompt}\n\nEl usuario te ha dicho por voz: "{prompt}"'
            payload = json.dumps(
                {"contents": [{"parts": [{"text": full_prompt}]}]}
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and parts[0].get("text"):
                        return str(parts[0]["text"]).strip()
                raise RuntimeError("Respuesta vacía de Google Gemini API")

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            payload = json.dumps(
                {
                    "model": model,
                    "max_tokens": 256,
                    "system": self.system_prompt,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data.get("content", [])
                if content and content[0].get("text"):
                    return str(content[0]["text"]).strip()
                raise RuntimeError("Respuesta vacía de Anthropic API")

        # OpenAI / Groq / DeepSeek / OpenAI-compatible con Token
        base_url = str(profile.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        return self._consultar_openai_compatible(
            prompt=prompt,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
        )

    def _consultar_openai_compatible(
        self, prompt: str, base_url: str, model: str, api_key: str, timeout: float
    ) -> str:
        headers = {"Content-Type": "application/json", "User-Agent": "Bugsito/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 220,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {}).get("content", "")
                if msg:
                    return str(msg).strip()
            raise RuntimeError(f"Respuesta vacía desde {base_url}")

    def generar_respuesta(self, prompt: str) -> str:
        """
        Recorre los perfiles candidatos según el modo (`local`, `token`, `auto`)
        y devuelve la primera respuesta exitosa.
        """
        candidatos = self._orden_perfiles_candidatos()
        errores: list[str] = []

        for name, prof in candidatos:
            try:
                respuesta = self.consultar_perfil(prompt, name, prof)
                if respuesta:
                    print(
                        f"[Bugsito Genkit] Respuesta de '{name}' ({prof.get('provider')}/{prof.get('model')})",
                        file=sys.stderr,
                    )
                    return respuesta
            except Exception as e:
                errores.append(f"{name}: {e}")

        if errores:
            print(f"[Bugsito Genkit] Fallaron los perfiles LLM: {'; '.join(errores)}", file=sys.stderr)
        return f"Entendido. Procesando: {prompt}"

    def estado_perfiles(self) -> list[dict[str, Any]]:
        """Devuelve un resumen del estado y configuración de cada perfil LLM."""
        resumen: list[dict[str, Any]] = []
        for name, prof in self.profiles.items():
            ptype = prof.get("type", "local")
            provider = prof.get("provider", "ollama")
            model = prof.get("model", "")
            activo = name == self.active_profile
            if ptype == "local":
                endpoint = self.resolver_host_local(prof)
                cred_ok = True
            else:
                endpoint = prof.get("base_url", provider)
                cred_ok = bool(self.resolver_token(prof))

            resumen.append(
                {
                    "name": name,
                    "active": activo,
                    "type": ptype,
                    "provider": provider,
                    "model": model,
                    "endpoint": endpoint,
                    "configured": cred_ok,
                }
            )
        return resumen
