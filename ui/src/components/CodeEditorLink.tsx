import { SquareCode } from "lucide-react";

/**
 * A token is never a legitimate part of this URL.
 *
 * The Code Editor the workshop deploys signs a browser in with a one-time `tkn`
 * parameter. `/api/health` publishes the origin only, so a URL that still
 * carries one either came from a hand-edited environment variable or from a
 * participant pasting their own address bar into config. Rendering it would put
 * a credential into every screenshot of this header, so the link is dropped and
 * the reason is written to the console rather than swallowed.
 */
const TOKEN_PARAMETER = /[?&]tkn=/i;

/**
 * The one way into the Code Editor, used by the header and by Shop's Lab 1
 * callout.
 *
 * One component rather than two links, because the refusal above has to hold in
 * both places: a rule that lives at one of two call sites is not a rule.
 */
export function CodeEditorLink(
  { href, className }: { href: string | null; className?: string },
) {
  const target = href?.trim() ?? "";
  if (!target) return null;
  if (TOKEN_PARAMETER.test(target)) {
    console.warn(
      "Refusing to render a Code Editor link: the URL carries a tkn= session token.",
    );
    return null;
  }
  return (
    <a
      className={className ? `code-editor-link ${className}` : "code-editor-link"}
      href={target}
      target="_blank"
      rel="noopener"
    >
      <SquareCode size={15} aria-hidden="true" />
      Code Editor
    </a>
  );
}
