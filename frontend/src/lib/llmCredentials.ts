/** Browser-local LLM credentials. Sent as X-LLM-* headers on API calls. */

export interface LlmCredentials {
  apiKey: string;
  baseUrl: string;
  model: string;
  criticApiKey: string;
  criticBaseUrl: string;
  criticModel: string;
}

export const EMPTY_LLM_CREDENTIALS: LlmCredentials = {
  apiKey: "",
  baseUrl: "",
  model: "",
  criticApiKey: "",
  criticBaseUrl: "",
  criticModel: "",
};

export const LLM_CREDENTIALS_KEY = "vnss-llm-credentials-v1";

export const LLM_HEADER = {
  apiKey: "X-LLM-Api-Key",
  baseUrl: "X-LLM-Base-Url",
  model: "X-LLM-Model",
  criticApiKey: "X-LLM-Critic-Api-Key",
  criticBaseUrl: "X-LLM-Critic-Base-Url",
  criticModel: "X-LLM-Critic-Model",
} as const;

function asString(v: unknown): string {
  return typeof v === "string" ? v : "";
}

export function loadLlmCredentials(): LlmCredentials {
  try {
    const raw = localStorage.getItem(LLM_CREDENTIALS_KEY);
    if (!raw) return { ...EMPTY_LLM_CREDENTIALS };
    const parsed = JSON.parse(raw) as Partial<LlmCredentials>;
    if (!parsed || typeof parsed !== "object") return { ...EMPTY_LLM_CREDENTIALS };
    return {
      apiKey: asString(parsed.apiKey),
      baseUrl: asString(parsed.baseUrl),
      model: asString(parsed.model),
      criticApiKey: asString(parsed.criticApiKey),
      criticBaseUrl: asString(parsed.criticBaseUrl),
      criticModel: asString(parsed.criticModel),
    };
  } catch {
    return { ...EMPTY_LLM_CREDENTIALS };
  }
}

export function saveLlmCredentials(c: LlmCredentials): void {
  try {
    localStorage.setItem(
      LLM_CREDENTIALS_KEY,
      JSON.stringify({
        apiKey: c.apiKey.trim(),
        baseUrl: c.baseUrl.trim(),
        model: c.model.trim(),
        criticApiKey: c.criticApiKey.trim(),
        criticBaseUrl: c.criticBaseUrl.trim(),
        criticModel: c.criticModel.trim(),
      })
    );
  } catch {
    /* ignore quota / private mode */
  }
}

export function clearLlmCredentials(): void {
  try {
    localStorage.removeItem(LLM_CREDENTIALS_KEY);
  } catch {
    /* ignore */
  }
}

/** Attach stored credentials so the backend can proxy the user's own model. */
export function applyLlmHeaders(headers: Headers): void {
  const c = loadLlmCredentials();
  if (c.apiKey) headers.set(LLM_HEADER.apiKey, c.apiKey);
  if (c.baseUrl) headers.set(LLM_HEADER.baseUrl, c.baseUrl);
  if (c.model) headers.set(LLM_HEADER.model, c.model);
  if (c.criticApiKey) headers.set(LLM_HEADER.criticApiKey, c.criticApiKey);
  if (c.criticBaseUrl) headers.set(LLM_HEADER.criticBaseUrl, c.criticBaseUrl);
  if (c.criticModel) headers.set(LLM_HEADER.criticModel, c.criticModel);
}
