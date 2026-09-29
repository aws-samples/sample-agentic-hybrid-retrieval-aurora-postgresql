import { ChevronRight } from "lucide-react";
import { Link } from "wouter";
import { categoryHref, editorialStories, storyHref } from "../shopStories";

/**
 * Alex's three needs as full-width bands, the apple.com product-page rhythm:
 * a dark band with the photograph full width, then two split bands that
 * alternate image and copy. Each band links to its category and to the scoped
 * search for the same need, the request the walkthrough above also sends.
 */
const bands = [
  {
    topic: "Headphones",
    tone: "dark",
    layout: "hero",
    image: "/assets/images/mosaic/alex-focus-editorial-v3.webp",
    width: 1600,
    height: 1200,
    alt: "Graphite headphones beside a laptop on Alex’s desk",
    title: "Find his focus.",
    description: "Headphones for clearer calls and deep work.",
  },
  {
    topic: "Monitors",
    tone: "grey",
    layout: "split",
    image: "/assets/images/mosaic/alex-screen-space-editorial-v1.webp",
    width: 1600,
    height: 1200,
    alt: "A monitor with room for code and documentation on Alex’s desk",
    title: "Make room for his work.",
    description: "Compare screen resolution and USB-C laptop charging.",
  },
  {
    topic: "Chairs",
    tone: "light",
    layout: "split-flip",
    image: "/assets/images/mosaic/alex-workspace-editorial-v3.webp",
    width: 1600,
    height: 1200,
    alt: "Alex’s finished workspace: a mesh chair at an oak standing desk with two monitors and headphones",
    title: "Bring his workspace together.",
    description: "Compare a monitor and chair, with specifications and reviews for each choice.",
  },
] as const;

export function ShopEditorialBands({ real }: { real: boolean }) {
  return (
    <div id="alexs-brief" className="shop-journey shop-bands">
      {bands.map((band) => {
        const story = editorialStories.find((candidate) => candidate.topic === band.topic);
        const id = `shop-band-${band.topic.toLowerCase()}`;
        return (
          <section
            key={band.topic}
            className="shop-band"
            data-tone={band.tone}
            data-layout={band.layout}
            aria-labelledby={id}
          >
            <div className="shop-band-inner">
              <div className="shop-band-copy">
                <h2 id={id}>{band.title}</h2>
                <p className="shop-band-sub">{band.description}</p>
                {story ? (
                  <p className="shop-band-links">
                    <Link href={categoryHref(story, real)}>
                      Shop {band.topic.toLowerCase()}
                      <ChevronRight size={16} aria-hidden="true" />
                    </Link>
                    <Link href={storyHref(story, real)}>
                      Find {band.topic.toLowerCase()} for Alex
                      <ChevronRight size={16} aria-hidden="true" />
                    </Link>
                  </p>
                ) : null}
              </div>
              <img
                className="shop-band-image"
                src={band.image}
                alt={band.alt}
                width={band.width}
                height={band.height}
                loading="lazy"
                decoding="async"
              />
              {story ? (
                <div className="shop-band-notes">
                  <p>{story.situation}</p>
                  <p><strong>What matters.</strong> {story.considerations}</p>
                </div>
              ) : null}
            </div>
          </section>
        );
      })}
    </div>
  );
}
