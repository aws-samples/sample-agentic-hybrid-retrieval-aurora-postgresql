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
 *
 * `#` is in the character class because a fragment carries the token just as far
 * as a query does: `code.example.aws/#tkn=8f2c` is pasted, screenshotted and
 * shared exactly like `?tkn=8f2c`, and the browser sends neither to the server
 * any less publicly than the other. A rule that reads only the query string
 * would have refused one spelling of the same credential and rendered the other.
 */
const TOKEN_PARAMETER = /[?&#]tkn=/i;

/**
 * The only scheme this link may carry.
 *
 * `href` reaches here from process configuration, which is a hand-edited
 * environment variable on a workshop machine, and an `href` is one of the places
 * a `javascript:` URL executes. Nothing else is a Code Editor either: `data:`,
 * `file:` and a bare `http:` origin are all a misconfiguration rather than a
 * destination, and the workshop publishes the editor over TLS.
 *
 * Parsed rather than prefix-matched, so `https:/\evil` and ` https://…` are
 * decided by the same parser the browser would use rather than by a string test
 * that disagrees with it.
 */
function isHttpsUrl(candidate: string): boolean {
  try {
    return new URL(candidate).protocol === "https:";
  } catch {
    // A relative path cannot be parsed without a base, and it cannot be a Code
    // Editor origin either.
    return false;
  }
}

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
  if (!isHttpsUrl(target)) {
    console.warn(
      "Refusing to render a Code Editor link: the URL is not an https: address.",
    );
    return null;
  }
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
