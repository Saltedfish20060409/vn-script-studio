/** True when stored icon is a legacy emoji / free text, not a glyph key. */
export function isGlyphKey(icon?: string | null): boolean {
  return Boolean(icon && /^[a-z][a-z0-9_]*$/i.test(icon.trim()));
}
