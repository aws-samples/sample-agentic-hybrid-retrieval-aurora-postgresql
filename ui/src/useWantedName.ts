import { useEffect, useState } from "react";
import { api } from "./api";
import type { MosaicLabMission } from "./labMissions";
import type { SearchResponse } from "./types";

/**
 * The wanted product's title, read live.
 *
 * A run that returned the product names it itself. A run that did not (the
 * fault a lab exists to show) cannot, so the title is looked up from the
 * catalog by id; the manifest never carries a second copy of it. Null until a
 * title is known, so a failed lookup leaves the caller's plain fallback.
 */
export function useWantedName(
  mission: MosaicLabMission | null | undefined,
  response: SearchResponse | null,
): string | null {
  const productId = mission?.target_product_ids[0];
  const served = response?.results.find((product) => product.product_id === productId)?.title;
  const [lookedUp, setLookedUp] = useState<{ id: number; title: string } | null>(null);
  useEffect(() => {
    if (productId === undefined || served) return;
    let active = true;
    api.product(productId).then((detail) => {
      if (active) setLookedUp({ id: productId, title: detail.title });
    }).catch(() => {
      // Callers read fine with a generic name when the lookup fails.
    });
    return () => { active = false; };
  }, [productId, served]);
  if (served) return served;
  return lookedUp && lookedUp.id === productId ? lookedUp.title : null;
}
