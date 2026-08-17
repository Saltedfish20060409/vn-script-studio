import { describe, expect, it } from "vitest";
import {
  changeLocale,
  enCoversZh,
  getLocale,
  t,
} from "./i18n";

describe("i18n", () => {
  it("translates known keys with parameter substitution", () => {
    changeLocale("zh");
    expect(t("settings.activeModel", { model: "deepseek-chat" })).toBe(
      "当前生效：deepseek-chat"
    );
    changeLocale("en");
    expect(t("settings.activeModel", { model: "deepseek-chat" })).toBe(
      "Active: deepseek-chat"
    );
  });

  it("falls back to zh and returns the key when absent everywhere", () => {
    changeLocale("en");
    expect(t("nav.write")).toBe("Write");
    changeLocale("zh");
    expect(t("nav.write")).toBe("写作");
    expect(t("no.such.key.anywhere")).toBe("no.such.key.anywhere");
  });

  it("en dictionary covers every zh key", () => {
    expect(enCoversZh()).toBe(true);
  });

  it("persists and changes locale", () => {
    const before = getLocale();
    changeLocale(before === "zh" ? "en" : "zh");
    const after = getLocale();
    expect(after === "zh" || after === "en").toBe(true);
    expect(after).not.toBe(before);
    changeLocale("zh");
  });
});
