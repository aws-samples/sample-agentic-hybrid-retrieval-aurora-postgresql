// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { showcaseCatalogPage } from "../showcase";
import { ProductAnswer } from "./ProductAnswer";
import { ResultProductCard } from "./ResultProductCard";

afterEach(cleanup);
const products = showcaseCatalogPage({}, 0, 2).products;
it("places each actual recommendation after its first named paragraph, once", () => {
  const text = `${products[0].title} suits the first need.\n\nThen consider **${products[1].model}** for the second need.\n\n${products[0].title} remains the first choice.`;
  const { container } = render(<ProductAnswer text={text} products={products} />);
  const blocks = container.querySelector(".product-answer")!.children;
  expect([...blocks].map((el) => el.tagName)).toEqual(["P", "OL", "P", "OL", "P"]);
  expect([...container.querySelectorAll(".result-product-card")].map((el) => el.getAttribute("data-product-id"))).toEqual(products.map((p) => String(p.product_id)));
  expect(container.querySelectorAll("img")).toHaveLength(2);
});
it("keeps streamed prose ahead of cards and preserves every unmatched recommendation", () => {
  const { rerender, container } = render(<ProductAnswer text={products[0].title} products={products} complete={false} />);
  expect(container.querySelectorAll(".result-product-card")).toHaveLength(0);
  rerender(<ProductAnswer text="Here are two suggestions." products={products} />);
  expect(container.querySelectorAll(".result-product-card")).toHaveLength(2);
  expect(container.querySelector(".product-answer")!.firstElementChild!.tagName).toBe("P");
});
it("renders a catalog rating and leaves absent ratings honest", () => {
  const { rerender } = render(<ResultProductCard product={{ ...products[0], rating: 4.7, review_count: 81 }} />);
  expect(screen.getByLabelText("4.7 out of 5 from 81 reviews")).toBeTruthy();
  rerender(<ResultProductCard product={{ ...products[0], rating: null, review_count: 0 }} />);
  expect(screen.getByText("No ratings yet")).toBeTruthy();
  expect(screen.queryByText("4.7")).toBeNull();
});
