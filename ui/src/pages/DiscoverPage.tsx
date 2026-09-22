import { useCatalogSource } from "../catalogSource";
import { ArrowRight, Check } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";
import { alexBrief } from "../alexBrief";
import { CatalogSearchComposer } from "../components/CatalogSearchComposer";
import { WorkspaceWalkthrough } from "../components/WorkspaceWalkthrough";
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
  const { real } = useCatalogSource();
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

  function search(query: string) {
    navigate("/catalog?" + new URLSearchParams({ q: query, view: "results" }));
  }

  return (
    <div className="discover-experience">
      <section className="discover-hero" aria-labelledby="discover-title">
        <header className="discover-heading">
          <h1 id="discover-title" className="commerce-display">
            A room built around <span>the way <span className="discover-heading-accent">you</span> work.</span>
          </h1>
        </header>
        <div className="discover-studio">
          <WorkspaceWalkthrough real={real} />
          <section id="alex-profile" className="discover-hero-content" aria-labelledby="alex-profile-title" tabIndex={-1}>
            <div className="discover-alex-intro">
              <img src="/assets/images/mosaic/alex-shopper-v1.jpg" alt="Alex" width={88} height={88} />
              <div>
                <h2 id="alex-profile-title">Meet Alex.</h2>
                <p className="discover-alex-role">{alexBrief.role}</p>
              </div>
            </div>
            <blockquote className="discover-alex-quote">“{alexBrief.quote}”</blockquote>
            <p className="discover-alex-bio">{alexBrief.description}</p>
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
                      <Link key={story.topic} href={categoryHref(story, real)}>{story.topic}</Link>
                    ))}
                  </nav>
                </dd>
              </div>
            </dl>
            <a className="discover-primary-link" href="#alexs-brief">Explore Alex’s brief</a>
          </section>
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
              onSubmit={search}
              placeholder="What would make work feel better?"
              showSuggestions={false}
              suggestionsOnType={false}
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
                <Link className="discover-category-tile" href={storyHref(story, real)} aria-label={`Explore ${story.title.toLowerCase()}`}>
                  <img src={story.image} alt={story.imageAlt} width={story.imageWidth} height={story.imageHeight} loading="lazy" decoding="async" />
                  <h3>{story.title}.</h3>
                </Link>
                <p className="discover-need-situation">{story.situation}</p>
                <div className="discover-need-considerations">
                  <h4>What matters</h4>
                  <p>{story.considerations}</p>
                </div>
                <Link className="discover-story-link" href={storyHref(story, real)}>Find {story.topic.toLowerCase()} for Alex <ArrowRight size={16} aria-hidden="true" /></Link>
              </article>
            ))}
          </div>
        </section>

        <section className="discover-shop-invitation" aria-labelledby="discover-shop-title">
          <div>
            <h2 id="discover-shop-title">Now, find the pieces that fit.</h2>
            <p>Explore the workspace edit and compare the details that make a difference.</p>
          </div>
          <Link className="discover-primary-link" href="/catalog">Shop the workspace <ArrowRight size={16} aria-hidden="true" /></Link>
        </section>
        <p className="discover-image-note">Alex is a fictional shopper. Workspace imagery is AI-generated and illustrative.</p>
      </div>
    </div>
  );
}
