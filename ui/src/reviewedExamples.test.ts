import { describe, expect, it } from 'vitest';
import { reviewedExamples, reviewedProductSummary } from './reviewedExamples';
import type { ProductSummary } from './types';
const review = reviewedExamples.cases[1].products[1];
const product = { product_id: review.product_id, sku: review.parent_asin, source_dataset: reviewedExamples.dataset_id, sources: [{ revision: review.source_record_sha256 }] } as ProductSummary;
describe('reviewed product facts', () => {
  it('shows source-bound facts for the current product', () => { expect(reviewedProductSummary(product)).toBe(review.card_summary); });
  it.each([{ source_dataset: 'old-catalog' }, { sku: 'wrong-variant' }, { sources: [{ revision: 'changed' }] }, { sources: [] }])('hides facts when source identity differs', change => { expect(reviewedProductSummary({ ...product, ...change } as ProductSummary)).toBeNull(); });
});
