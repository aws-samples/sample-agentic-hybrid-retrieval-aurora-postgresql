export function MosaicMark({ className = "brand-glyph" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1.5" y="1.5" width="29" height="29" rx="2.5" fill="var(--brand-mark)" />
      <text x="16" y="24" textAnchor="middle" fontFamily="var(--sans)" fontSize="22" fontWeight="650" fill="#000000">M</text>
    </svg>
  );
}
