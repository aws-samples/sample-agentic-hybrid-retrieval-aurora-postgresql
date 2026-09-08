import { Link } from "wouter";
import { categoryProductImage } from "../media";

const monitorAccessories = [
  {
    key: "monitor-arms", title: "Monitor arms", imageSeed: 427431,
    description: "Reclaim desk space. Match the VESA pattern, display weight and desk clamp range.",
  },
  {
    key: "docking-stations", title: "Docks & connections", imageSeed: 483208,
    description: "Bring your devices together. Check your laptop, display ports and supported resolution.",
  },
  {
    key: "cable-management", title: "Cable management", imageSeed: 467721,
    description: "Keep the surface clear. Choose a tray or cable route that suits your desk.",
  },
];

/** Accessories are category relationships; these links do not assert product fit. */
export function ProductComplements({ categoryKey }: { categoryKey: string }) {
  if (!["ultrawide-monitors", "productivity-monitors"].includes(categoryKey)) return null;
  return (
    <section className="product-complements" aria-labelledby="product-complements-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">The rest of your desk</p>
          <h2 id="product-complements-title">Complete your setup</h2>
        </div>
      </div>
      <div className="product-complements-grid">
        {monitorAccessories.map((item) => (
          <article key={item.key}>
            <Link href={`/catalog?domain=home_office&category_key=${item.key}`} className="product-complement-image" aria-label={`Explore ${item.title.toLowerCase()}`}>
              <img src={categoryProductImage({ product_id: item.imageSeed, category_key: item.key, domain: "home_office" })} alt="" loading="lazy" width={1200} height={800} />
            </Link>
            <h3>{item.title}</h3>
            <p>{item.description}</p>
            <Link className="product-complement-link" href={`/catalog?domain=home_office&category_key=${item.key}`}>Explore {item.title.toLowerCase()}</Link>
          </article>
        ))}
      </div>
    </section>
  );
}
