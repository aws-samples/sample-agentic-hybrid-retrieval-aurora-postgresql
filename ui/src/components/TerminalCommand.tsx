import { Check, Copy, SquareTerminal } from "lucide-react";
import { useState } from "react";
import { CLIPBOARD_UNAVAILABLE } from "./CodeBlock";

/** A command to run in Code Editor's terminal, with a button that copies it. */
export function TerminalCommand({ command, lead = "In Code Editor, run" }: { command: string; lead?: string }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");

  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard access is unavailable");
      }
      await navigator.clipboard.writeText(command);
      setCopyError("");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
      setCopyError(CLIPBOARD_UNAVAILABLE);
    }
  }

  return (
    <>
      <p className="terminal-command">
        <SquareTerminal aria-hidden="true" size={15} />
        <small>{lead}</small>
        <code>{command}</code>
        <button aria-label={`Copy ${command}`} className="icon-button" onClick={() => void copy()} title="Copy command" type="button">
          {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
        </button>
      </p>
      {copyError ? <p className="code-copy-error" role="alert">{copyError}</p> : null}
    </>
  );
}
