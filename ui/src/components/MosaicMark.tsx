export function MosaicMark({ className = "brand-glyph" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1.5" y="1.5" width="29" height="29" rx="2.5" fill="currentColor" />
      <path
        d="M6.5 24V8h3.3l6.2 8.35L22.2 8h3.3v16h-3.45v-9.6L17.6 20.5h-3.2l-4.45-6.1V24H6.5Z"
        fill="#fffaf2"
      />
    </svg>
  );
}
