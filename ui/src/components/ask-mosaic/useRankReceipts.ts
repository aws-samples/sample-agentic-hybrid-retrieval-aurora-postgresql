import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import type { RetrievalRunResponse } from "../../types";
import { pickName } from "./comparison";
import { ROW_LIMIT, rowsFromReceipt } from "./rankRows";

export type ReceiptState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; receipt: RetrievalRunResponse };

/**
 * Reads each saved search the answer ran, by its retrieval run id, and the
 * names of the products at the top of each. `/api/retrieval/events/{id}` holds
 * the rows the database wrote while it fused, which is what the ranks and bars
 * print. Nothing is requested until `enabled`, so Builder view off costs nothing.
 */
export function useRankReceipts(runIds: string[], enabled: boolean, known: Map<number, string>) {
  const key = runIds.join(",");
  const [receipts, setReceipts] = useState<Record<string, ReceiptState>>({});
  const [fetchedNames, setFetchedNames] = useState<Map<number, string>>(new Map());

  useEffect(() => {
    if (!enabled) return undefined;
    let current = true;
    const ids = key ? key.split(",") : [];
    setReceipts(Object.fromEntries(ids.map((id) => [id, { status: "loading" } as ReceiptState])));
    for (const id of ids) {
      api.retrievalEvent(id).then(
        (receipt) => {
          if (current) setReceipts((all) => ({ ...all, [id]: { status: "ready", receipt } }));
        },
        () => {
          if (current) setReceipts((all) => ({ ...all, [id]: { status: "error" } }));
        },
      );
    }
    return () => { current = false; };
  }, [enabled, key]);

  const missing = useMemo(() => {
    const wanted = new Set<number>();
    for (const state of Object.values(receipts)) {
      if (state.status !== "ready") continue;
      for (const row of rowsFromReceipt(state.receipt, new Map(), ROW_LIMIT)) {
        if (!known.has(row.productId)) wanted.add(row.productId);
      }
    }
    return [...wanted].filter((id) => !fetchedNames.has(id)).sort((a, b) => a - b);
  }, [receipts, known, fetchedNames]);

  const requested = useRef(new Set<number>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    for (const id of missing) {
      if (requested.current.has(id)) continue;
      requested.current.add(id);
      api.product(id).then(
        (product) => {
          if (mounted.current) setFetchedNames((all) => new Map(all).set(id, pickName(product)));
        },
        () => {
          // A name that cannot be read is printed as the listing id instead.
        },
      );
    }
  }, [missing]);

  const names = useMemo(() => new Map([...fetchedNames, ...known]), [fetchedNames, known]);
  return { receipts, names };
}
