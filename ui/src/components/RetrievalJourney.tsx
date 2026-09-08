import { coreMosaicLabs, stageLabels } from "../labMissions";

const scenes = {
  retrieve: {
    image: "/assets/images/mosaic/alex-focus-editorial-v3.webp",
    alt: "Graphite headphones beside a laptop on Alex’s desk",
    title: "Find his focus.",
    description: "Headphones for clearer calls and deep work.",
  },
  rank: {
    image: "/assets/images/mosaic/alex-comfort-editorial-v3.webp",
    alt: "An adjustable mesh chair in a bright, modern home office",
    title: "Make long days comfortable.",
    description: "Compare chairs around the support Alex needs.",
  },
  reason: {
    image: "/assets/images/mosaic/alex-workspace-editorial-v3.webp",
    alt: "A home office with a standing desk, two monitors, laptop, headphones and a mesh chair",
    title: "Bring his workspace together.",
    description: "Understand the choices, and why each piece fits.",
  },
};

export function RetrievalJourney() {
  return (
    <section className="shop-journey" aria-label="Alex’s workspace: an illustrated Retrieve, Rank, Reason journey">
      <ol className="shop-journey-sequence" aria-label="Retrieve, Rank and Reason: Alex’s workspace story" tabIndex={0}>
        {coreMosaicLabs.map((mission, index) => {
          const scene = scenes[mission.stage as keyof typeof scenes];
          if (!scene) return null;
          return (
            <li key={mission.id}>
              <div className="shop-journey-stage">
                <span className="shop-journey-number">{String(index + 1).padStart(2, "0")}</span>
                <span>{stageLabels[mission.stage]}</span>
                <span className="shop-journey-rule" aria-hidden="true" />
              </div>
              <img src={scene.image} alt={scene.alt} width={1600} height={1200} decoding="async" />
              <div className="shop-journey-caption">
                <h2>{scene.title}</h2>
                <p>{scene.description}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
