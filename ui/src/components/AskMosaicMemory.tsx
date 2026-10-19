import { useEffect, useId, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { memoryRecordText } from "../memoryRecordText";
import type { MemoryConnectionStatus, SessionMemorySnapshot } from "../types";

export function useAskMosaicMemory(open: boolean) {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState<MemoryConnectionStatus["memory_status"] | "loading">("loading");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setStatus("loading");
    api.memoryStatus().then((connection) => {
      if (current) setStatus(connection.memory_status === "connected" && connection.configuration?.status !== "ACTIVE"
        ? "unavailable" : connection.memory_status);
    }).catch(() => { if (current) setStatus("unavailable"); });
    return () => { current = false; };
  }, [open, revision]);
  return { enabled, setEnabled, status, retry: () => setRevision((value) => value + 1) };
}

export type AskMosaicMemoryControl = ReturnType<typeof useAskMosaicMemory>;

/** What the toggle does right now, in one sentence. Shown as a hint, not a status band. */
function memoryHint(memory: AskMosaicMemoryControl): string {
  if (memory.status === "loading") return "Checking AgentCore Memory.";
  if (memory.status === "not_configured") return "AgentCore Memory is not connected. You can still ask about products.";
  if (memory.status === "unavailable") return "AgentCore Memory is unavailable. Retry or turn memory off.";
  return memory.enabled
    ? "AgentCore Memory reads saved details and saves this chat."
    : "Memory is off. Follow-ups still use this conversation.";
}

/**
 * One row above the composer: the toggle and where the memories live. The
 * sentence about what it does sits in the toggle's tooltip and description;
 * it takes a line of its own only when memory cannot be used.
 */
export function MemoryControl({ memory, pending }: { memory: AskMosaicMemoryControl; pending: boolean }) {
  const connected = memory.status === "connected";
  const hint = memoryHint(memory);
  const hintId = useId();
  const blocked = memory.status === "unavailable" || memory.status === "not_configured";
  return <div className="ask-mosaic-memory-control">
    <label title={hint}>
      <input type="checkbox" checked={memory.enabled} disabled={pending || (!connected && !memory.enabled)}
        aria-describedby={hintId}
        onChange={(event) => memory.setEnabled(event.target.checked)} />Use saved memories</label>
    <Link href="/mosaic-labs/memory">View memories</Link>
    <p id={hintId} className={blocked ? undefined : "sr-only"}>{hint}
      {memory.status === "unavailable" && <button type="button" disabled={pending} onClick={memory.retry}>Retry connection</button>}
    </p>
  </div>;
}

export function MemoryReceipt({ memory }: { memory?: SessionMemorySnapshot }) {
  if (!memory?.enabled) return null;
  const records = memory.records ?? [];
  return <details className="ask-mosaic-memory-receipt">
    <summary>Memories used <span>{records.length}</span></summary>
    {memory.status !== "connected" ? <p>AgentCore Memory was not connected for this answer.</p> : <>
      <p>{records.length ? "These saved details helped interpret your request. Product facts still come from the catalog sources."
        : "No saved facts or preferences matched this request."} {memory.event_ids_read?.length ?? 0} earlier conversation events were read.</p>
      <ul>{records.map((record) => <li key={record.id}>
        <p>{memoryRecordText(record.text)}</p>
        <details><summary>Record details</summary><code>{record.id}</code><pre>{record.text}</pre></details>
      </li>)}</ul>
      {memory.write_status === "failed" ? <p role="alert">The answer is available, but this conversation could not be saved in AgentCore Memory.</p>
        : memory.write_status === "stored" ? <p>Conversation saved. AgentCore processes new memories in the background.</p> : null}
    </>}
    <p>New conversation starts a fresh chat and keeps saved memories.</p>
    <Link href="/mosaic-labs/memory">Inspect AgentCore Memory</Link>
  </details>;
}
