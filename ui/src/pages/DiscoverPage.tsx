import { Check, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";
import { CatalogSearchComposer } from "../components/CatalogSearchComposer";
import { GenerativeSearchIcon } from "../components/GenerativeSearchIcon";
import { categoryHref, editorialStories, storyHref } from "../discoverContent";
import { discoverData } from "../discoverData";
import { useNavigate } from "../navigation";
import "../discover.css";

export { editorialStories } from "../discoverContent";

export const intentionCategories = editorialStories.map(story => ({
  label: story.topic,
  domain: story.filters.domain!,
  categoryKey: story.filters.category_key!,
  image: story.image,
}));

export function DiscoverPage() {
  const navigate = useNavigate();
  const [searchCount, setSearchCount] = useState(
    () => discoverData.scope.peek()?.database.product_count,
  );

  useEffect(() => {
    let active = true;
    void discoverData.scope.load().then(scope => {
      if (active) setSearchCount(scope.database.product_count);
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  function search(query: string) {
    navigate("/catalog?" + new URLSearchParams({ q: query, view: "results" }));
  }

  return (
    <div className="discover-experience">
      <section className="discover-hero" aria-labelledby="discover-title">
        <header className="discover-heading">
          <h1 id="discover-title" className="commerce-display">
            A room built around <em>the way you work.</em>
          </h1>
          <p>Good choices start with the person using them. Let’s build a home office around the way Alex spends his day.</p>
        </header>

        <div className="discover-studio">
          <figure className="discover-hero-photo">
            <img
              src="/assets/images/mosaic/alex-workspace-editorial-v3.webp"
              alt="A sunlit home office with an oak standing desk, two monitors, laptop, headphones and mesh chair"
              width={1600}
              height={1200}
              fetchPriority="high"
            />
            <figcaption>A room to work toward.</figcaption>
          </figure>
          <div className="discover-hero-content">
            <div className="discover-alex-intro">
              <img src="/assets/images/mosaic/alex-shopper-v1.jpg" alt="Alex" width={88} height={88} />
              <h2>Meet Alex.</h2>
            </div>
            <p className="discover-alex-bio">A software engineer making space for good work at home. His day moves between writing code, team calls and time to concentrate.</p>
            <dl className="discover-brief">
              <div>
                <dt>Already in place</dt>
                <dd className="discover-ready-pieces">
                  <span><Check size={15} aria-hidden="true" /> Desk</span>
                  <span><Check size={15} aria-hidden="true" /> Laptop</span>
                </dd>
              </div>
              <div>
                <dt>Still to choose</dt>
                <dd>
                  <nav className="discover-hero-categories" aria-label="Workspace categories">
                    {editorialStories.map(story => (
                      <Link key={story.topic} href={categoryHref(story)}>{story.topic}</Link>
                    ))}
                  </nav>
                </dd>
              </div>
            </dl>
            <a className="discover-primary-link" href="#alexs-brief">Explore Alex’s brief</a>
          </div>
        </div>

        <div className="discover-search-row">
          <div>
            <h2>Start with what matters to you.</h2>
            <p>Follow Alex’s brief below, or describe your own.</p>
            {searchCount ? <p className="discover-search-scope">Search {searchCount.toLocaleString()} products</p> : null}
          </div>
          <div className="discover-search" role="search">
            <CatalogSearchComposer
              inputLabel="Search products"
              leadingIcon={<GenerativeSearchIcon size={20} />}
              onSubmit={search}
              placeholder="What would make work feel better?"
              showSuggestions={false}
              suggestionsOnType={false}
              submitIcon={<Send size={16} aria-hidden="true" />}
              submitIconOnly
            />
          </div>
        </div>
      </section>

      <div className="discover-body">
        <section id="alexs-brief" className="discover-section" aria-labelledby="discover-needs-title">
          <header className="discover-section-heading">
            <h2 id="discover-needs-title">Three needs. One working day.</h2>
            <p>Each choice has a job to do.</p>
          </header>
          <div className="discover-editorial-grid">
            {editorialStories.map(story => (
              <article key={story.topic} className="discover-need">
                <Link className="discover-category-tile" href={storyHref(story)} aria-label={`Explore ${story.title.toLowerCase()}`}>
                  <img src={story.image} alt={story.imageAlt} width={story.imageWidth} height={story.imageHeight} loading="lazy" decoding="async" />
                  <h3>{story.title}.</h3>
                </Link>
                <p className="discover-need-situation">{story.situation}</p>
                <div className="discover-need-considerations">
                  <h4>What matters</h4>
                  <p>{story.considerations}</p>
                </div>
                <Link className="discover-story-link" href={storyHref(story)}>Find {story.topic.toLowerCase()} for Alex</Link>
              </article>
            ))}
          </div>
        </section>

        <section className="discover-shop-invitation" aria-labelledby="discover-shop-title">
          <div>
            <h2 id="discover-shop-title">Now, find the pieces that fit.</h2>
            <p>Explore the workspace edit and compare the details that make a difference.</p>
          </div>
          <Link className="discover-primary-link" href="/catalog">Shop the workspace</Link>
        </section>
        <p className="discover-image-note">Alex is a fictional shopper. Workspace imagery is AI-generated and illustrative.</p>
      </div>
    </div>
  );
}
