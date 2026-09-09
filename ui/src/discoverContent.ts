import { mosaicLabManifest } from "./labMissions";
import type { SearchFilters } from "./types";

export type EditorialStory = {
  topic: string;
  title: string;
  situation: string;
  considerations: string;
  image: string;
  imageWidth: number;
  imageHeight: number;
  imageAlt: string;
  query: string;
  filters: Pick<SearchFilters, "domain" | "category_key">;
};

const storyContent = {
  "clear-calls": {
    topic: "Headphones",
    situation: "Home isn’t always quiet. Alex needs his teammates to hear his voice, even when there’s noise in the background.",
    considerations: "Start with microphone clarity. Then compare listening comfort and noise cancellation for focused work between calls.",
    image: "/assets/images/mosaic/alex-focus-editorial-v3.webp",
    imageWidth: 1600,
    imageHeight: 1200,
    imageAlt: "Graphite headphones beside a laptop and burgundy notebook on a felt desk mat",
  },
  "comfortable-days": {
    topic: "Chairs",
    situation: "A quick call becomes a long coding session. Alex wants a chair he can adjust to his body and the way he works.",
    considerations: "Look at lumbar support, seat depth and arm adjustments. A soft seat alone doesn’t tell the whole story.",
    image: "/assets/images/mosaic/alex-long-day-editorial-v1.webp",
    imageWidth: 1792,
    imageHeight: 1008,
    imageAlt: "A mesh office chair with a burgundy throw beside an oak desk in warm daylight",
  },
  "quiet-typing": {
    topic: "Keyboards",
    situation: "Alex takes notes while his teammates talk. He wants a keyboard that feels good to type on without taking over the call.",
    considerations: "Compare typing noise and switch feel. Then check the layout and wireless connection for his daily work.",
    image: "/assets/images/mosaic/ho-quiet-keyboards-01-catalog-3x2.webp",
    imageWidth: 1200,
    imageHeight: 800,
    imageAlt: "A cream mechanical keyboard with maroon keys on a warm stone surface",
  },
};

// Discover and Shop must send the same customer need to the same photographed category.
export const editorialStories: EditorialStory[] = mosaicLabManifest.playground.requests.flatMap(request => {
  const content = storyContent[request.id as keyof typeof storyContent];
  return content ? [{ ...content, title: request.shop_label, query: request.query, filters: request.filters }] : [];
});

export function categoryHref(story: EditorialStory): string {
  return "/catalog?" + new URLSearchParams(
    Object.entries(story.filters).filter((entry): entry is [string, string] =>
      typeof entry[1] === "string",
    ),
  );
}

export function storyHref(story: EditorialStory): string {
  const params = new URLSearchParams(categoryHref(story).split("?")[1]);
  params.set("q", story.query);
  params.set("view", "results");
  return "/catalog?" + params;
}
