import { Check, Copy } from "lucide-react";
import { useState } from "react";

export function CodeBlock({ code, label }: { code: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");

  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard access is unavailable");
      }
      await navigator.clipboard.writeText(code);
      setCopyError("");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
      setCopyError("Clipboard access is unavailable. Select the code and copy it manually.");
    }
  }

  return (
    <div className="code-block">
      <div className="code-toolbar">
        <span>{label}</span>
        <button type="button" className="icon-button" onClick={() => void copy()} title="Copy SQL">
          {copied ? <Check size={16} /> : <Copy size={16} />}
          <span className="sr-only">Copy SQL</span>
        </button>
      </div>
      {copyError ? <p className="code-copy-error" role="alert">{copyError}</p> : null}
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
