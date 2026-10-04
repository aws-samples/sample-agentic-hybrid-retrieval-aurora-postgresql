/**
 * The header's Ask Mosaic pill and Shop's panel live in different components, so
 * the pill asks for the panel with a window event. Shop answers it by opening the
 * panel; any other page navigates to Shop's `?ask=1` deep link instead.
 */
export const ASK_MOSAIC_EVENT = "mosaic:open-ask";

export const ASK_MOSAIC_DEEP_LINK = "/catalog?ask=1";

export function requestAskMosaic(): void {
  window.dispatchEvent(new Event(ASK_MOSAIC_EVENT));
}
