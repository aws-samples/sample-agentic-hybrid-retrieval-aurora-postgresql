/**
 * A short choice shown in full: one pill per option, the chosen one filled blue.
 * Buttons with `aria-pressed` in a labelled group, the pattern the memory picker uses.
 */
export function SegmentedControl<T extends string | number>({ label, options, value, onChange }: {
  label: string;
  options: ReadonlyArray<{ value: T; label: string }>;
  value: T | undefined;
  onChange: (value: T) => void;
}) {
  return (
    <div className="mosaic-segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
