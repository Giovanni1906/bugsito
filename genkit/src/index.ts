/**
 * Bugsito — Motor de Flujos LLM con Firebase Genkit
 * =================================================
 * Gestiona múltiples proveedores de LLM bajo una arquitectura unificada con Genkit:
 *   1. Modo Local por IP (`mode = "local"`): Ollama en LAN/Tailscale (Mac Mini o localhost)
 *      o servidores compatibles con OpenAI locales (LM Studio, vLLM, llama.cpp).
 *   2. Modo por Token (`mode = "token"`): Google Gemini (@genkit-ai/googleai),
 *      OpenAI, Groq, DeepSeek o Anthropic mediante API Key.
 *
 * Puede ejecutarse como:
 *   - Servidor HTTP local de baja latencia: `npm run serve` (puerto 3400)
 *   - Interfaz de desarrollo Genkit UI: `npm run genkit:ui`
 *   - Ejecución directa por CLI: `npm run ask -- "tu consulta"`
 */

import http from "node:http";
import { genkit, z } from "genkit";
import { googleAI } from "@genkit-ai/googleai";
import { ollama } from "genkitx-ollama";
import { openAI } from "genkitx-openai";

const DEFAULT_OLLAMA_HOST = process.env.BUGSITO_OLLAMA_HOST || "http://127.0.0.1:11434";
const DEFAULT_OLLAMA_MODEL = process.env.BUGSITO_OLLAMA_MODEL || "llama3.1:8b";
const DEFAULT_SYSTEM_PROMPT =
  "Eres Bugsito, el asistente de voz inteligente del sistema NixOS. " +
  "Responde siempre en español de forma natural, concisa y directa (máximo 1 o 2 oraciones breves). " +
  "Sin texto de relleno, sin markdown ni listas, optimizado para ser leído en voz alta por TTS.";

// Inicializar plugins dinámicamente según variables de entorno disponibles
const plugins: any[] = [
  ollama({
    models: [{ name: DEFAULT_OLLAMA_MODEL }],
    serverAddress: DEFAULT_OLLAMA_HOST,
  }),
];

if (process.env.GEMINI_API_KEY || process.env.GOOGLE_GENAI_API_KEY) {
  plugins.push(
    googleAI({
      apiKey: process.env.GEMINI_API_KEY || process.env.GOOGLE_GENAI_API_KEY,
    })
  );
}

if (process.env.OPENAI_API_KEY) {
  plugins.push(
    openAI({
      apiKey: process.env.OPENAI_API_KEY,
    })
  );
}

export const ai = genkit({
  plugins,
});

// Esquema de entrada del flujo de voz de Bugsito
export const VoiceQueryInputSchema = z.object({
  prompt: z.string().describe("Texto transcrito de la voz del usuario"),
  systemPrompt: z.string().optional().describe("Instrucciones del sistema para Bugsito"),
  mode: z.enum(["local", "token", "auto"]).default("auto"),
  provider: z
    .enum(["ollama", "googleai", "openai", "openai-compatible"])
    .default("ollama"),
  model: z.string().default(DEFAULT_OLLAMA_MODEL),
  host: z.string().optional().describe("URL o IP del servidor LLM local (ej. http://100.109.249.113:11434)"),
  baseUrl: z.string().optional().describe("Endpoint base para APIs compatibles con OpenAI"),
  apiKey: z.string().optional().describe("Token / API Key cuando se usa modo por token"),
});

export const VoiceQueryOutputSchema = z.object({
  response: z.string(),
  providerUsed: z.string(),
  modelUsed: z.string(),
  modeUsed: z.string(),
});

/**
 * Ejecuta una consulta contra un proveedor específico (Local por IP o Cloud por Token).
 */
async function executeProviderQuery(
  input: z.infer<typeof VoiceQueryInputSchema>
): Promise<z.infer<typeof VoiceQueryOutputSchema>> {
  const sysPrompt = input.systemPrompt || DEFAULT_SYSTEM_PROMPT;
  const fullPrompt = `${sysPrompt}\n\nEl usuario te ha dicho por voz: "${input.prompt}"`;

  // 1. MODO LOCAL POR IP (Ollama en red local / Tailscale)
  if (input.provider === "ollama") {
    const targetHost = (input.host || DEFAULT_OLLAMA_HOST).replace(/\/+$/, "");
    // Si coincide con el servidor Ollama configurado en la instancia de Genkit, usamos ai.generate
    if (targetHost === DEFAULT_OLLAMA_HOST.replace(/\/+$/, "")) {
      const result = await ai.generate({
        model: `ollama/${input.model}`,
        prompt: fullPrompt,
      });
      return {
        response: result.text.trim(),
        providerUsed: "ollama (genkit)",
        modelUsed: input.model,
        modeUsed: "local",
      };
    }

    // Si el perfil especifica otra IP en tiempo de ejecución, consultamos ese nodo Ollama
    const res = await fetch(`${targetHost}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: input.model,
        prompt: fullPrompt,
        stream: false,
      }),
    });
    if (!res.ok) {
      throw new Error(`Error HTTP ${res.status} conectando a Ollama en ${targetHost}`);
    }
    const data = (await res.json()) as { response?: string };
    return {
      response: (data.response || "").trim(),
      providerUsed: `ollama (${targetHost})`,
      modelUsed: input.model,
      modeUsed: "local",
    };
  }

  // 2. MODO POR TOKEN: Google Gemini vía Genkit
  if (input.provider === "googleai") {
    const apiKey = input.apiKey || process.env.GEMINI_API_KEY || process.env.GOOGLE_GENAI_API_KEY;
    if (!apiKey) {
      throw new Error("Falta GEMINI_API_KEY para el proveedor googleai en modo token.");
    }
    if (process.env.GEMINI_API_KEY || process.env.GOOGLE_GENAI_API_KEY) {
      const result = await ai.generate({
        model: `googleai/${input.model}`,
        prompt: fullPrompt,
      });
      return {
        response: result.text.trim(),
        providerUsed: "googleai (genkit)",
        modelUsed: input.model,
        modeUsed: "token",
      };
    }
    // Si la API key vino en el request dinámicamente
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${input.model}:generateContent?key=${apiKey}`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: fullPrompt }] }],
      }),
    });
    if (!res.ok) {
      throw new Error(`Error HTTP ${res.status} en Gemini API`);
    }
    const data = (await res.json()) as any;
    const text = data?.candidates?.[0]?.content?.parts?.[0]?.text || "";
    return {
      response: text.trim(),
      providerUsed: "googleai",
      modelUsed: input.model,
      modeUsed: "token",
    };
  }

  // 3. MODO POR TOKEN: OpenAI o proveedores compatibles (Groq, DeepSeek, vLLM)
  const apiKey = input.apiKey || process.env.OPENAI_API_KEY || process.env.GROQ_API_KEY || process.env.DEEPSEEK_API_KEY;
  const baseUrl = (input.baseUrl || "https://api.openai.com/v1").replace(/\/+$/, "");

  if (input.provider === "openai" && process.env.OPENAI_API_KEY && baseUrl === "https://api.openai.com/v1") {
    const result = await ai.generate({
      model: `openai/${input.model}`,
      prompt: fullPrompt,
    });
    return {
      response: result.text.trim(),
      providerUsed: "openai (genkit)",
      modelUsed: input.model,
      modeUsed: "token",
    };
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }

  const res = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      model: input.model,
      messages: [
        { role: "system", content: sysPrompt },
        { role: "user", content: input.prompt },
      ],
      temperature: 0.4,
    }),
  });
  if (!res.ok) {
    throw new Error(`Error HTTP ${res.status} en endpoint OpenAI-compatible (${baseUrl})`);
  }
  const data = (await res.json()) as any;
  const text = data?.choices?.[0]?.message?.content || "";
  return {
    response: text.trim(),
    providerUsed: input.provider,
    modelUsed: input.model,
    modeUsed: input.mode,
  };
}

/**
 * Flujo oficial de Genkit para procesar consultas de voz de Bugsito.
 */
export const bugsitoVoiceFlow = ai.defineFlow(
  {
    name: "bugsitoVoiceFlow",
    inputSchema: VoiceQueryInputSchema,
    outputSchema: VoiceQueryOutputSchema,
  },
  async (input) => {
    return await executeProviderQuery(input);
  }
);

/**
 * Servidor HTTP ligero para que el widget GTK de Bugsito consulte el flujo Genkit sin latencia de arranque.
 */
function startServer(port = 3400) {
  const server = http.createServer(async (req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok", service: "bugsito-genkit" }));
      return;
    }

    if (req.method === "POST" && (req.url === "/bugsitoVoiceFlow" || req.url === "/ask")) {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", async () => {
        try {
          const parsed = JSON.parse(body || "{}");
          // Soporta formato directo o envoltorio `{ data: ... }` de Genkit
          const payload = parsed.data ? parsed.data : parsed;
          const validated = VoiceQueryInputSchema.parse(payload);
          const output = await bugsitoVoiceFlow(validated);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(output));
        } catch (err: any) {
          res.writeHead(500, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: err?.message || String(err) }));
        }
      });
      return;
    }

    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Ruta no encontrada" }));
  });

  server.listen(port, "127.0.0.1", () => {
    console.log(`[Bugsito Genkit] Servidor de flujos escuchando en http://127.0.0.1:${port}`);
  });
}

// CLI Entrypoint
const args = process.argv.slice(2);
if (args.includes("--serve")) {
  const portIndex = args.indexOf("--port");
  const port = portIndex !== -1 && args[portIndex + 1] ? Number(args[portIndex + 1]) : 3400;
  startServer(port);
} else if (args.includes("--ask")) {
  const idx = args.indexOf("--ask");
  const promptText = args.slice(idx + 1).join(" ") || "Hola Bugsito";
  bugsitoVoiceFlow({
    prompt: promptText,
    mode: (process.env.BUGSITO_LLM_MODE as any) || "auto",
    provider: "ollama",
    model: DEFAULT_OLLAMA_MODEL,
  })
    .then((out) => {
      console.log(JSON.stringify(out));
    })
    .catch((err) => {
      console.error(`[Bugsito Genkit Error] ${err.message}`);
      process.exit(1);
    });
}
