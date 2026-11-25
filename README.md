# Bugsito (antes Jarvis) — Asistente de Voz Interactivo para Linux / Wayland

**Bugsito** es un asistente de voz interactivo con interfaz visual tipo **Reactor Arc / Bola de Energía** renderizada en tiempo real con **GTK3 + Cairo + GtkLayerShell** (y fallback automático a ventana flotante en X11), transcripción neuronal local ultrarrápida con `whisper.cpp`, síntesis de voz natural con **Piper TTS**, y un motor **Multi-LLM gestionado con Firebase Genkit** que soporta tanto modelos locales por IP/Tailscale como modelos en la nube por Token.

Está diseñado para funcionar en dos escenarios:
1. **Integrado de forma nativa con [`dotfiles-nixos`](https://github.com/Giovanni1906/dotfiles-nixos)**: Adopta en vivo la paleta de colores del tema activo (`~/dotfiles/tema/tema.conf`), habla con el motor de voz del sistema (`~/dotfiles/utils/voz.sh`), deduce la IP de la Mac Mini desde `~/dotfiles/.env` y se activa con `SUPER + SPACE` en Hyprland.
2. **De forma autónoma en cualquier otra PC o distribución Linux**: Usa su propia configuración en `~/.config/bugsito/config.toml` y `~/.config/bugsito/.env`, descarga automáticamente los modelos de voz si faltan y permite elegir cualquier LLM local o por API Token.

---

## Arquitectura del Proyecto

```text
bugsito/
├── bugsito.sh               # Lanzador universal (modo toggle UI y despachador CLI)
├── config.example.toml      # Plantilla de configuración general, temas, skills y perfiles LLM
├── .env.example             # Plantilla de secretos (IPs locales y API Tokens para Genkit)
├── flake.nix                # Empaquetado declarativo para Nix / NixOS
├── pyproject.toml           # Empaquetado estándar Python
├── scripts/
│   └── install-client.sh    # Instalador de comandos globales (`bugsito` y alias `jarvis`)
├── genkit/                  # Motor Firebase Genkit (TypeScript / Node.js)
│   ├── package.json         # Dependencias: genkit, @genkit-ai/googleai, genkitx-ollama, genkitx-openai
│   └── src/index.ts         # Flujo `bugsitoVoiceFlow`, Genkit Developer UI y servidor HTTP local
└── bugsito/                 # Núcleo en Python
    ├── cli.py               # Comandos CLI (`toggle`, `ask`, `llm`, `genkit-serve`, `genkit-ui`, `doctor`)
    ├── config.py            # Lector de config.toml, .env y paleta en vivo de dotfiles (`tema.conf`)
    ├── ui/orb.py            # Widget Cairo Reactor Arc (Wayland GtkLayerShell + fallback flotante X11)
    ├── audio/
    │   ├── stt.py           # Captura 16kHz mono con ffmpeg y transcripción local con whisper-cli
    │   └── tts.py           # Conector a `~/dotfiles/utils/voz.sh` o motor Piper TTS / espeak-ng propio
    ├── llm/
    │   └── genkit_client.py # Cliente y gestor Multi-LLM con Genkit (modo `local`, `token` y `auto`)
    └── orchestrator/
        └── router.py        # Enrutador de órdenes: terminal, proyectos, sistema, skills custom y LLM
```

---

## Motor Multi-LLM con Firebase Genkit (Modo Local por IP o por Token)

Bugsito gestiona sus modelos de lenguaje a través de **Genkit** soportando tres modos de operación (`mode` en `~/.config/bugsito/config.toml` o `BUGSITO_LLM_MODE` en `~/.config/bugsito/.env`):

| Modo | Descripción | Cuándo usarlo |
| --- | --- | --- |
| **`local`** | Conecta únicamente por **IP / URL** a servidores en tu red local o Tailscale (ej. **Ollama** en la Mac Mini `http://100.x.y.z:11434`, Ollama en `http://127.0.0.1:11434`, vLLM o LM Studio). | Privacidad 100% local o dentro de tu red Tailscale sin gastar tokens. |
| **`token`** | Conecta mediante **API Key / Token** a modelos cloud a través de Genkit (**Google Gemini**, **OpenAI**, **Groq**, **DeepSeek**, **Anthropic**). | Cuando estás fuera de tu red local o quieres usar modelos frontera en otra PC. |
| **`auto`** *(por defecto)* | Intenta primero el perfil activo (`active_profile`) y, si no hay conexión o falla, recorre automáticamente la lista `fallback_order` (por ejemplo: Mac Mini por IP → Gemini por Token → Ollama local). | Ideal para laptops o uso mixto: usa tu servidor local cuando está disponible y pasa a token automáticamente si estás fuera. |

### Comandos para gestionar los LLMs

```bash
# Ver todos los perfiles configurados, su modo (local/token) y si tienen credenciales listas
bugsito llm list

# Cambiar el modo global de operación
bugsito llm mode local     # Solo servidores por IP (Ollama / LAN / Tailscale)
bugsito llm mode token     # Solo proveedores en la nube con API Token
bugsito llm mode auto      # Automático con fallback

# Elegir qué perfil de LLM usar por defecto
bugsito llm use mac-ollama
bugsito llm use local-ollama
bugsito llm use gemini
bugsito llm use openai
bugsito llm use groq
bugsito llm use deepseek

# Probar la conexión y respuesta del perfil activo (o de uno específico)
bugsito llm test
bugsito llm test gemini
```

### Servidor de Flujos y Developer UI de Firebase Genkit

El directorio [`genkit/`](./genkit) incluye el proyecto **Firebase Genkit** con el flujo `bugsitoVoiceFlow`:

```bash
# Levantar el servidor local de flujos Genkit en http://127.0.0.1:3400
bugsito genkit-serve

# Abrir la interfaz gráfica de desarrollo de Firebase Genkit (Genkit Developer UI)
# para inspeccionar trazas, probar prompts y evaluar modelos
bugsito genkit-ui
```

> Si el servidor `bugsito genkit-serve` está activo en el puerto `3400`, el cliente de Bugsito enruta las peticiones a través del flujo `bugsitoVoiceFlow` de Genkit. Si no está levantado, Bugsito ejecuta el adaptador directo sin latencia de arranque en frío.

---

## Instalación

### Opción A: Integrado con el ecosistema `dotfiles-nixos`

En el repositorio `~/dotfiles`, el instalador `./init.sh` gestiona automáticamente a Bugsito:

1. Al ejecutar `./init.sh` (o `./init.sh bugsito`), te pregunta si deseas instalar/sincronizar **Bugsito** (`[S/n]`).
2. Si eliges que sí, lo clona en **`~/Proyectos/bugsito`** (el mismo directorio donde vive `~/Proyectos/context-hub`), enlaza `~/.config/bugsito/config.toml` y ejecuta `scripts/install-client.sh --non-interactive`.
3. En Hyprland, el atajo **`SUPER + SPACE`** lanza `bugsito` con los colores en vivo de `~/dotfiles/tema/tema.conf` y la voz de `~/dotfiles/utils/voz.sh`.

### Opción B: En cualquier otra PC o distribución Linux

1. **Clonar el repositorio e instalar el cliente CLI**:
   ```bash
   git clone https://github.com/Giovanni1906/bugsito.git ~/Proyectos/bugsito
   cd ~/Proyectos/bugsito
   ./scripts/install-client.sh
   ```
   Esto instala el comando `bugsito` (y el alias `jarvis`) en `~/.local/bin` y crea `~/.config/bugsito/config.toml` junto con `~/.config/bugsito/.env` (permisos `600`).

2. **Configurar tu LLM (IP local o Token)**:
   Edita `~/.config/bugsito/.env`:
   ```bash
   # Para usar un servidor Ollama por IP:
   export BUGSITO_LLM_MODE="local"
   export BUGSITO_LLM_PROFILE="local-ollama"
   export BUGSITO_OLLAMA_HOST="http://127.0.0.1:11434"

   # O para usar un proveedor por Token (ej. Gemini u OpenAI):
   export BUGSITO_LLM_MODE="token"
   export BUGSITO_LLM_PROFILE="gemini"
   export GEMINI_API_KEY="tu_api_key_aqui"
   ```

3. **Con Nix (sin instalar dependencias manualmente)**:
   ```bash
   nix run github:Giovanni1906/bugsito
   ```

---

## Uso y Comandos de Voz

- **Activar / Enviar por voz**: Presiona `SUPER + SPACE` (o ejecuta `bugsito`). Aparecerá la bola de energía en la esquina inferior derecha. Habla al micrófono y presiona **`Espacio`** (o `SUPER + SPACE` de nuevo, o haz clic en el orbe) para procesar la orden. Presiona **`Escape`** para cancelar.
- **Comandos de voz integrados**:
  - **Terminal**: *"Escribe en la terminal git status"*, *"Corre en la terminal npm test"*.
  - **Proyectos**: *"Abre el proyecto dotfiles"*, *"Abre el proyecto bugsito en cursor"*, *"Abre el proyecto context-hub en terminal"*.
  - **Sistema y Multimedia**: *"Abre la terminal"*, *"Abre el navegador"*, *"Abre el gestor de archivos"*, *"Sube el volumen"*, *"Baja el volumen"*, *"Silencio"*, *"Bloquea la pantalla"*.
  - **Agentes de IA y Skills**: *"Inicia Hermes"*, *"Abre Claude"*, *"Inicia Antigravity"*, *"Abre Lazydocker"*.
  - **Conversación con IA (Genkit)**: Cualquier pregunta o consulta abierta es respondida por el LLM activo y leída en voz alta.
- **Uso desde terminal (sin micrófono)**:
  ```bash
  bugsito ask "¿Cuál es el comando para limpiar generaciones en NixOS?"
  bugsito ask --speak "Dime un resumen rápido de qué es NixOS"
  bugsito doctor
  ```
