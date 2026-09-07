import { api } from "./api";
import { cachedRequest } from "./cachedRequest";
import { editorialStories, merchandisingDoors } from "./discoverContent";

export function createDiscoverData() {
  return {
    counts: cachedRequest(() => api.catalogCounts(merchandisingDoors.map(door => door.filters))),
    voices: cachedRequest(() => api.reviewHighlights()),
    summary: cachedRequest(() => api.summary()),
    stories: editorialStories.map(story => ({
      topic: story.topic,
      products: cachedRequest(() => api.catalog(story.filters, 0, 3, "rating")),
    })),
  };
}

export const discoverData = createDiscoverData();

/** Start the near-hero reads while React loads the Discover route. */
export function preloadDiscover() {
  void discoverData.voices.load().catch(() => {});
  void discoverData.counts.load().catch(() => {});
  void discoverData.summary.load().catch(() => {});
}
