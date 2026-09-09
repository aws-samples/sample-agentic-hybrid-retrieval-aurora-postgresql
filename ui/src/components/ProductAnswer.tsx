import type { ReactNode } from "react";
import Markdown from "react-markdown";
import type { Root, RootContent } from "mdast";
import { productImageMap } from "../media";
import type { AgentCitation, ProductSummary } from "../types";
import { ResultProductCard } from "./ResultProductCard";

type TextNode = { type: string; value?: string; children?: TextNode[] };
const words = (value: string) => value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
const nodeText = (node: TextNode): string => node.value ?? node.children?.map(nodeText).join("") ?? "";

/** Insert cards after the first paragraph naming a returned product, never from arbitrary answer text. */
export function productCardPlacement(products: ProductSummary[]) {
  return () => (tree: Root) => {
    const remaining = new Set(products.map((p) => p.product_id));
    const marker = (ids: number[]): RootContent => ({ type: "paragraph", children: [], data: { hName: "div", hProperties: { "data-product-cards": ids.join(",") } } });
    const walk = (parent: TextNode) => {
      if (!parent.children) return;
      const children: TextNode[] = [];
      for (const child of parent.children) {
        walk(child); children.push(child);
        if (child.type !== "paragraph") continue;
        const text = ` ${words(nodeText(child))} `;
        const matches = products.filter((p) => remaining.has(p.product_id) && [p.title, p.model].some((name) => name.length >= 4 && text.includes(` ${words(name)} `)));
        if (matches.length) { matches.forEach((p) => remaining.delete(p.product_id)); children.push(marker(matches.map((p) => p.product_id))); }
      }
      parent.children = children;
    };
    walk(tree as TextNode);
    if (remaining.size) tree.children.push(marker(products.filter((p) => remaining.has(p.product_id)).map((p) => p.product_id)));
  };
}

export function ProductAnswer({ text, products, citations = [], complete = true, label = "Mosaic’s picks for Alex", renderCard, renderSearchLink }: {
  text: string; products: ProductSummary[]; citations?: AgentCitation[]; complete?: boolean; label?: string;
  renderCard?: (product: ProductSummary, position: number) => ReactNode;
  renderSearchLink?: (product: ProductSummary) => ReactNode;
}) {
  const images = productImageMap(products);
  return <section className="product-answer" aria-label={complete && products.length ? label : undefined}>
    <Markdown remarkPlugins={complete ? [productCardPlacement(products)] : []} components={{
      div: ({ node, children, ...props }) => {
        const ids = node?.properties["data-product-cards"] ?? node?.properties.dataProductCards;
        if (typeof ids !== "string") return <div {...props}>{children}</div>;
        return <ol className="answer-product-cards">{ids.split(",").map((id) => {
          const index = products.findIndex((p) => p.product_id === Number(id));
          if (index < 0) return null;
          const product = products[index];
          const count = new Set(citations.filter((c) => c.product_id === product.product_id).map((c) => c.evidence_id)).size;
          return <li key={id} value={index + 1}>{renderCard ? renderCard(product, index + 1) : <ResultProductCard product={product} imageSrc={images.get(product.product_id)} rank={index + 1} footer={count || renderSearchLink ? <>{count ? <span className="result-product-evidence">{count} cited {count === 1 ? "source" : "sources"}</span> : null}{renderSearchLink?.(product)}</> : undefined} />}</li>;
        })}</ol>;
      },
    }}>{text}</Markdown>
  </section>;
}
