export function memoryRecordText(text: string): string {
  try {
    const value = JSON.parse(text);
    if (typeof value === "string") return value;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const key of ["preference", "fact", "summary", "situation"]) {
        if (typeof value[key] === "string" && value[key].trim()) return value[key];
      }
      if (Array.isArray(value.turns)) {
        const situations = value.turns
          .map((turn: unknown) => turn && typeof turn === "object" && "situation" in turn ? turn.situation : null)
          .filter((situation: unknown): situation is string => typeof situation === "string" && Boolean(situation.trim()));
        if (situations.length) return situations.join("\n\n");
      }
    }
    return "This memory contains structured details. Open Record details to inspect what AgentCore saved.";
  } catch { /* Summary and episodic records use XML fragments. */ }
  if (text.trim().startsWith("<")) {
    const xml = new DOMParser().parseFromString(`<memory>${text}</memory>`, "application/xml");
    if (!xml.querySelector("parsererror")) return xml.documentElement.textContent?.trim() || text;
  }
  return text;
}
