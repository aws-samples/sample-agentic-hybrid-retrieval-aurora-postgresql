import { coreMosaicLabs, stageLabels } from "../labMissions";

const scenes = {
  retrieve: {
    image: "/assets/images/mosaic/alex-focus-editorial-v3.webp",
    alt: "Graphite headphones beside a laptop on Alex’s desk",
    title: "Find his focus.",
    description: "Headphones for clearer calls and deep work.",
  },
  rank: {
    image: "/assets/images/mosaic/alex-screen-space-editorial-v1.webp",
    alt: "A monitor with room for code and documentation on Alex’s desk",
    title: "Make room for his work.",
    description: "Compare screen resolution and USB-C laptop charging.",
  },
  reason: {
    image: "/assets/images/mosaic/alex-workspace-after.jpg",
    alt: "The vision for Alex’s workspace: the same desk with a mesh chair, two monitors and headphones",
    title: "Bring his workspace together.",
    description: "Compare a monitor and chair, with specifications and reviews for each choice.",
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
              <img src={scene.image} alt={scene.alt} width={1168} height={784} decoding="async" />
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
