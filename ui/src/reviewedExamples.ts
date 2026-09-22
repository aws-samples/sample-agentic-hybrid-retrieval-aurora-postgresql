import selection from '../../data/evals/reviewed_product_examples.json';
import type { ProductSummary } from './types';

export const reviewedExamples = selection;
export type ReviewedProduct = typeof selection.cases[number]['products'][number];
export function reviewedSourceMatches(product: ProductSummary, review: ReviewedProduct): boolean {
  return product.source_dataset === selection.dataset_id
    && product.product_id === review.product_id && product.sku === review.parent_asin
    && product.sources.some(source => source.revision === review.source_record_sha256);
}
export function reviewedProductSummary(product: ProductSummary): string | null {
  const review = selection.cases.flatMap<ReviewedProduct>(item => item.products).find(item => item.product_id === product.product_id);
  return review && reviewedSourceMatches(product, review) ? review.card_summary : null;
}
