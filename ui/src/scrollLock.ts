/**
 * Locks the page scroll behind an overlay and returns the restore.
 *
 * Hiding the body's scrollbar widens the viewport, so the page shifts sideways
 * at the exact moment an overlay starts sliding in. Reserving the scrollbar's
 * width as body padding keeps the page still under classic scrollbars; overlay
 * scrollbars measure zero and leave the padding untouched.
 */
export function lockBodyScroll(): () => void {
  const { body, documentElement } = document;
  const scrollbarWidth = window.innerWidth - documentElement.clientWidth;
  const previousOverflow = body.style.overflow;
  const previousPaddingRight = body.style.paddingRight;
  if (scrollbarWidth > 0) {
    const basePadding =
      Number.parseFloat(window.getComputedStyle(body).paddingRight) || 0;
    body.style.paddingRight = `${basePadding + scrollbarWidth}px`;
  }
  body.style.overflow = "hidden";
  return () => {
    body.style.overflow = previousOverflow;
    body.style.paddingRight = previousPaddingRight;
  };
}
