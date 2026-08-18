import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyLlmHeaders,
  clearLlmCredentials,
  EMPTY_LLM_CREDENTIALS,
  LLM_CREDENTIALS_KEY,
  LLM_HEADER,
  loadLlmCredentials,
  saveLlmCredentials,
} from "./llmCredentials";

function createMockStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => {
      store.set(k, String(v));
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", createMockStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("llmCredentials", () => {
  it("returns empty credentials when nothing is stored", () => {
    expect(loadLlmCredentials()).toEqual(EMPTY_LLM_CREDENTIALS);
  });

  it("round-trips key, url and model", () => {
    saveLlmCredentials({
      apiKey: " sk-test ",
      baseUrl: " https://api.deepseek.com ",
      model: " deepseek-chat ",
      criticApiKey: "sk-c",
      criticBaseUrl: "https://c.example",
      criticModel: "critic",
    });
    expect(loadLlmCredentials()).toEqual({
      apiKey: "sk-test",
      baseUrl: "https://api.deepseek.com",
      model: "deepseek-chat",
      criticApiKey: "sk-c",
      criticBaseUrl: "https://c.example",
      criticModel: "critic",
    });
  });

  it("survives corrupt JSON", () => {
    localStorage.setItem(LLM_CREDENTIALS_KEY, "{not json");
    expect(loadLlmCredentials()).toEqual(EMPTY_LLM_CREDENTIALS);
  });

  it("applies only non-empty fields as headers", () => {
    saveLlmCredentials({
      ...EMPTY_LLM_CREDENTIALS,
      apiKey: "sk-x",
      baseUrl: "https://api.moonshot.cn",
      model: "moonshot-v1-32k",
    });
    const headers = new Headers();
    applyLlmHeaders(headers);
    expect(headers.get(LLM_HEADER.apiKey)).toBe("sk-x");
    expect(headers.get(LLM_HEADER.baseUrl)).toBe("https://api.moonshot.cn");
    expect(headers.get(LLM_HEADER.model)).toBe("moonshot-v1-32k");
    expect(headers.has(LLM_HEADER.criticApiKey)).toBe(false);
  });

  it("clears stored credentials", () => {
    saveLlmCredentials({ ...EMPTY_LLM_CREDENTIALS, apiKey: "sk-x" });
    clearLlmCredentials();
    expect(loadLlmCredentials().apiKey).toBe("");
  });
});
