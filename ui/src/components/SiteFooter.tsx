import { Banknote, CreditCard, Nfc, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import { RETRIEVAL_SURFACE } from "../navigation";
import { MosaicMark } from "./MosaicMark";

const sourceRepositoryUrl =
  "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql";

/**
 * The payment plates, and why the artwork in them is generic.
 *
 * A storefront footer names how you would pay, and the plate treatment here is
 * the one every shop uses. What is inside each plate is not: Visa, Mastercard,
 * Amex, PayPal, Apple Pay and Google Pay marks are trademarks licensed to
 * merchants who accept that card, and this catalog accepts nothing.
 *
 * The repository already ships one third-party mark, `assets/icons/github-mark.svg`,
 * beside a `GITHUB-MARK-LICENSE.txt` naming its source, author and MIT licence.
 * That is the bar for shipping a brand mark here, and none of the card networks
 * publish theirs under terms that clear it, so there is no truthful licence file
 * to put next to the artwork.
 *
 * `art` is the seam. Swapping in official assets is this array plus files in
 * `ui/public/assets/icons/`, each with its own licence or permission note:
 *
 *   { id: "visa", label: "Visa",
 *     art: <img alt="" aria-hidden="true" src="/assets/icons/visa.svg" /> }
 *
 * Nothing else in the footer changes.
 */
interface PaymentMark {
  id: string;
  label: string;
  art: ReactNode;
}

const paymentMarks: PaymentMark[] = [
  {
    id: "card",
    label: "Credit and debit",
    art: <CreditCard size={15} aria-hidden="true" />,
  },
  {
    id: "contactless",
    label: "Contactless",
    art: <Nfc size={15} aria-hidden="true" />,
  },
  {
    id: "wallet",
    label: "Digital wallet",
    art: <Wallet size={15} aria-hidden="true" />,
  },
  {
    id: "transfer",
    label: "Bank transfer",
    art: <Banknote size={15} aria-hidden="true" />,
  },
];

/**
 * Every column entry is a route or a document that exists.
 *
 * A shop footer is where invented links accumulate: About, Careers, Returns,
 * Accessibility, a newsletter field that posts nowhere. Mosaic has none of those
 * pages, and a footer full of dead links is a worse imitation of a real store
 * than a short one. The storefront column is Shop's real domain filters, the
 * second is the Playground's three lenses under the names they carry there, and
 * the third leaves for documentation that is genuinely the substrate.
 */
const footerColumns: Array<{
  id: string;
  heading: string;
  links: Array<{ label: string; href: string; external?: boolean }>;
}> = [
  {
    id: "shop",
    heading: "Shop",
    links: [
      { label: "Discover", href: "/" },
      { label: "All products", href: "/catalog" },
      { label: "Electronics", href: "/catalog?domain=consumer_electronics" },
      { label: "Running & fitness", href: "/catalog?domain=running_fitness" },
      { label: "Workspace", href: "/catalog?domain=home_office" },
    ],
  },
  {
    id: "behind",
    heading: "Behind the results",
    links: [
      { label: "Retrieve, rank, reason", href: RETRIEVAL_SURFACE.path },
      { label: "Vector index at scale", href: "/mosaic-labs/hnsw" },
      { label: "Catalog studio", href: "/mosaic-labs/studio" },
    ],
  },
  {
    id: "built",
    heading: "Built with",
    links: [
      {
        label: "Amazon Aurora PostgreSQL",
        href: "https://aws.amazon.com/rds/aurora/",
        external: true,
      },
      {
        label: "pgvector",
        href: "https://github.com/pgvector/pgvector",
        external: true,
      },
      {
        label: "Amazon Bedrock",
        href: "https://aws.amazon.com/bedrock/",
        external: true,
      },
    ],
  },
];

/**
 * The storefront's closing band.
 *
 * Three things a shop's footer does, and one this one has to. It repeats the
 * brand, it opens the routes the header has no room for, and it names how you
 * would pay: ordinary furniture whose absence is what made every surface end on
 * a bare grid. The fourth is the disclosure, and it is not optional here. A page
 * that shows prices, stock, reviews and payment methods has to say plainly that
 * none of it charges anything and none of it is real, because everything else on
 * the page is built to be believed.
 */
export function SiteFooter({ inert = false }: { inert?: boolean }) {
  return (
    <footer
      className="site-footer"
      inert={inert || undefined}
      aria-hidden={inert || undefined}
    >
      <div className="site-footer-inner">
        <div className="site-footer-payment">
          <span className="site-footer-eyebrow">Payment methods</span>
          <ul aria-label="Payment methods">
            {paymentMarks.map((mark) => (
              <li key={mark.id}>
                {mark.art}
                {mark.label}
              </li>
            ))}
          </ul>
        </div>

        <div className="site-footer-top">
          <div className="site-footer-brand">
            <Link className="site-footer-mark" href="/" aria-label="Mosaic home">
              <MosaicMark />
              <strong>Mosaic</strong>
            </Link>
            <p>
              A demonstration storefront, built to show how retrieval becomes a
              recommendation.
            </p>
            <a
              className="site-footer-source"
              href={sourceRepositoryUrl}
              rel="noreferrer"
              target="_blank"
            >
              <img
                alt=""
                aria-hidden="true"
                height="15"
                src="/assets/icons/github-mark.svg"
                width="15"
              />
              Read the source
            </a>
          </div>

          <nav className="site-footer-columns" aria-label="Footer">
            {footerColumns.map((column) => (
              <div className="site-footer-column" key={column.id}>
                <h2>{column.heading}</h2>
                <ul>
                  {column.links.map((link) => (
                    <li key={link.href}>
                      {link.external ? (
                        <a href={link.href} rel="noreferrer" target="_blank">
                          {link.label}
                        </a>
                      ) : (
                        <Link href={link.href}>{link.label}</Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        <div className="site-footer-legal">
          <p>
            Nothing here charges a card. Products, prices, reviews and
            availability are synthetic data built for this workshop.
          </p>
          <p className="site-footer-copyright">
            © Amazon.com, Inc. or its affiliates. Sample code under MIT-0.
          </p>
        </div>
      </div>
    </footer>
  );
}
