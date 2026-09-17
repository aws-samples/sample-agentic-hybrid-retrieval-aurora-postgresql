const notices: Record<string, { title: string; help: string }> = {
  insufficient_evidence: {
    title: "The sources do not answer this yet",
    help: "A product can be in the catalog without sources for every question. Ask about a specific feature or inspect the sources used.",
  },
  unsupported_requirements: {
    title: "These requirements are not confirmed",
    help: "The available sources do not confirm the requested features or compatibility. Check the product details before choosing.",
  },
  unrelated_request: {
    title: "This question is outside the catalog",
    help: "Ask about a product, compare its features, or check what its sources say.",
  },
  no_supported_catalog_answer: {
    title: "Mosaic could not answer from these sources",
    help: "Try a specific product or feature. The recorded steps show what was checked.",
  },
};

export function DeclinedAnswer({ answer, reason, className }: {
  answer: string;
  reason?: string | null;
  className: string;
}) {
  // Older coverage responses carry the unmatched term itself as the reason.
  const notice = reason ? notices[reason] ?? {
    title: "Nothing in the catalog matches part of this request",
    help: "This is a catalog gap, not a retrieval fault. Try different words or drop the term named above.",
  } : notices.no_supported_catalog_answer;
  return <section className={className} aria-label="Declined answer">
    <h3>{notice.title}</h3>
    <p>{answer}</p>
    <small>{notice.help}</small>
  </section>;
}
