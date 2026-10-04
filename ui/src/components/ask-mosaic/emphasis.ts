import type { ProductSummary } from "../../types";

function escapePattern(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Emphasize only products present in the grounded recommendation contract.
 *
 * The cited synthesis model is not required to author presentation Markdown.
 * Applying emphasis at the UI boundary makes product names consistent without
 * changing the answer of record or inferring names from untrusted prose.
 */
export function boldRecommendationNames(
  answer: string,
  recommendations: ProductSummary[],
) {
  const names = Array.from(
    new Set(
      recommendations.flatMap((product) => [
        product.title.trim(),
        `${product.brand} ${product.model}`.trim(),
      ]),
    ),
  )
    .filter((name) => name.length >= 5)
    .sort((left, right) => right.length - left.length);
  if (!names.length) return answer;

  const productName = new RegExp(
    `(${names.map(escapePattern).join("|")})`,
    "gi",
  );
  return answer
    .split(/(\*\*[^*]+\*\*)/g)
    .map((segment) => (
      segment.startsWith("**")
        ? segment
        : segment.replace(productName, "**$1**")
    ))
    .join("");
}
