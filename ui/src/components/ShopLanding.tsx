import { Check, Sparkles } from "lucide-react";
import { useEffect } from "react";
import { Link } from "wouter";
import { alexBrief } from "../alexBrief";
import { categoryHref, editorialStories } from "../shopStories";
import { ShopEditorialBands } from "./ShopEditorialBands";
import { WorkspaceWalkthrough } from "./WorkspaceWalkthrough";

/**
 * The invitation to Ask Mosaic. Shop renders it once: as the landing's closing
 * band, or as a compact note beside the search once there are results.
 */
export function AskMosaicInvite({ compact, returning, onOpen }: {
  compact: boolean;
  /** An answered conversation exists, so the action resumes rather than starts. */
  returning: boolean;
  onOpen: () => void;
}) {
  return (
    <aside
      className={compact ? "shop-console-note is-compact" : "shop-band shop-ask-band"}
      data-tone={compact ? undefined : "grey"}
      aria-label="What Ask Mosaic does"
    >
      <div className="shop-console-note-intro">
        <h2>{returning ? "Keep comparing your options." : "A little help choosing?"}</h2>
        <p>Tell Mosaic what matters. Get a considered shortlist, with the details behind each pick.</p>
      </div>
      <button
        className="mosaic-ask-button shop-console-note-action"
        type="button"
        aria-label="Ask Mosaic"
        aria-expanded={false}
        onClick={onOpen}
      >
        <Sparkles size={15} aria-hidden="true" />
        {returning ? "Return to Ask Mosaic" : "Ask Mosaic"}
      </button>
    </aside>
  );
}

/** Alex's profile header links here, so the brief has to take focus on arrival. */
function useProfileHash() {
  useEffect(() => {
    function focusProfile() {
      if (window.location.hash !== "#alex-profile") return;
      const profile = document.getElementById("alex-profile");
      profile?.focus({ preventScroll: true });
      profile?.scrollIntoView({ block: "start", behavior: "instant" });
    }
    const frame = window.requestAnimationFrame(focusProfile);
    window.addEventListener("hashchange", focusProfile);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", focusProfile);
    };
  }, []);
}

/**
 * Shop before a search: who Alex is, his three needs as editorial bands, then
 * the invitation to Ask Mosaic. Every link lands on a Shop category or a scoped
 * search; lab instructions stay in the guide and the Playground.
 */
export function ShopLanding({ real, returning, onAsk }: {
  real: boolean;
  returning: boolean;
  onAsk: () => void;
}) {
  useProfileHash();
  return (
    <div className="shop-landing">
      <div className="shop-band shop-alex-band" data-tone="grey">
        <div className="shop-band-inner shop-alex-studio">
          <WorkspaceWalkthrough real={real} />
          <section
            id="alex-profile"
            className="shop-alex-profile"
            aria-labelledby="alex-profile-title"
            tabIndex={-1}
          >
            <div className="shop-alex-intro">
              <img src="/assets/images/mosaic/alex-shopper-v1.jpg" alt="Alex" width={88} height={88} />
              <div>
                <h2 id="alex-profile-title">Meet Alex.</h2>
                <p className="shop-alex-role">{alexBrief.role}</p>
              </div>
            </div>
            <blockquote className="shop-alex-quote">“{alexBrief.quote}”</blockquote>
            <p className="shop-alex-bio">{alexBrief.description}</p>
            <dl className="shop-alex-brief">
              <div>
                <dt>Already in place</dt>
                <dd className="shop-alex-ready">
                  <span><Check size={15} aria-hidden="true" /> Desk</span>
                  <span><Check size={15} aria-hidden="true" /> Laptop</span>
                </dd>
              </div>
              <div>
                <dt>Still to choose</dt>
                <dd>
                  <nav className="shop-alex-categories" aria-label="Workspace categories">
                    {editorialStories.map((story) => (
                      <Link key={story.topic} href={categoryHref(story, real)}>{story.topic}</Link>
                    ))}
                  </nav>
                </dd>
              </div>
            </dl>
            <a className="shop-alex-brief-link" href="#alexs-brief">Explore Alex’s brief</a>
          </section>
        </div>
      </div>
      <ShopEditorialBands real={real} />
      <AskMosaicInvite compact={false} returning={returning} onOpen={onAsk} />
      <p className="shop-image-note">
        Alex is a fictional shopper. Workspace imagery is AI-generated and illustrative.
      </p>
    </div>
  );
}
