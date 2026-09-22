import { sourceFilters } from "./catalogSource";
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
  "more-screen-space": {
    topic: "Monitors",
    situation: "Code in one window, reference material in another. Alex wants a clear, comfortable view without constantly switching between them.",
    considerations: "Compare screen size, resolution and connections. A USB-C port alone doesn’t tell you whether it carries video, charges a laptop, or both.",
    image: "/assets/images/mosaic/ho-productivity-monitors-atelier-32-catalog-3x2.webp",
    imageWidth: 1536,
    imageHeight: 1024,
    imageAlt: "A flat desktop monitor with a burgundy and sand screen on an oak desk, with its complete stand visible",
  },
};

// Discover and Shop must send the same customer need to the same photographed category.
export const editorialStories: EditorialStory[] = mosaicLabManifest.playground.requests.flatMap(request => {
  const content = storyContent[request.id as keyof typeof storyContent];
  return content ? [{ ...content, title: request.shop_label, query: request.query, filters: request.filters }] : [];
});

export function categoryHref(story: EditorialStory, real = false): string {
  return "/catalog?" + new URLSearchParams(
    Object.entries(sourceFilters(story.filters, real)).filter((entry): entry is [string, string] =>
      typeof entry[1] === "string",
    ),
  );
}

export function storyHref(story: EditorialStory, real = false): string {
  const params = new URLSearchParams(categoryHref(story, real).split("?")[1]);
  params.set("q", story.query);
  params.set("view", "results");
  return "/catalog?" + params;
}
