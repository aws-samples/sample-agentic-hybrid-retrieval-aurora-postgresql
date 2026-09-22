import { ArrowRight, ChevronDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { alexBrief } from "../alexBrief";

export function AlexProfile({ onOpen }: { onOpen: () => void }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  function dismiss() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    headingRef.current?.focus({ preventScroll: true });
    const closeOutside = (event: Event) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="site-shopper-profile">
      <button
        ref={buttonRef}
        type="button"
        className="site-shopper"
        aria-label="Alex’s profile"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? id : undefined}
        onClick={() => {
          if (!open) onOpen();
          setOpen(!open);
        }}
      >
        <img src="/assets/images/mosaic/alex-shopper-v1.jpg" alt="" width={46} height={46} />
        <span>Alex</span>
        <ChevronDown className="site-shopper-chevron" size={14} aria-hidden="true" />
      </button>
      {open && (
        <section id={id} className="alex-profile-card" role="dialog" aria-labelledby={`${id}-title`}>
          <button className="site-icon alex-profile-close" type="button" aria-label="Close Alex’s profile" onClick={dismiss}>
            <X size={17} aria-hidden="true" />
          </button>
          <div className="alex-profile-heading">
            <img src="/assets/images/mosaic/alex-shopper-v1.jpg" alt="" width={64} height={64} />
            <div>
              <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>Alex</h2>
              <p>{alexBrief.role}</p>
            </div>
          </div>
          <p className="alex-profile-bio">Your workspace: headphones, a chair and a monitor for your home office.</p>
          <a className="alex-profile-link" href="/discover#alex-profile" onClick={() => setOpen(false)}>View your workspace brief <ArrowRight size={16} aria-hidden="true" /></a>
        </section>
      )}
    </div>
  );
}
