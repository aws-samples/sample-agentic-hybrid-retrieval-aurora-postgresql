/**
 * The header's Ask Mosaic pill and Shop's panel live in different components, so
 * the pill asks for the panel with a window event. Shop answers it by opening the
 * panel; any other page navigates to Shop's `?ask=1` deep link instead.
 */
export const ASK_MOSAIC_EVENT = "mosaic:open-ask";

export const ASK_MOSAIC_DEEP_LINK = "/catalog?ask=1";

/** Shop reads this parameter into Ask Mosaic's composer; it is never a Shop search. */
export const ASK_MOSAIC_PROMPT_PARAM = "prompt";

/** Opens Ask Mosaic with `prompt` ready to send, leaving Shop's own search alone. */
export function askMosaicPromptHref(prompt: string): string {
  return `${ASK_MOSAIC_DEEP_LINK}&${ASK_MOSAIC_PROMPT_PARAM}=${encodeURIComponent(prompt)}`;
}

export function requestAskMosaic(): void {
  window.dispatchEvent(new Event(ASK_MOSAIC_EVENT));
}
