import { Banknote, CreditCard, Nfc, Wallet } from "lucide-react";
import { Link } from "wouter";
import { MosaicMark } from "./MosaicMark";

/**
 * The payment families the storefront names, drawn rather than branded.
 *
 * A card network's mark is a trademark licensed to merchants who accept that
 * card, and this catalog accepts nothing: printing Visa's or Mastercard's mark
 * here would assert a commercial relationship that does not exist, in a public
 * sample repository. These four are the payment families a shopper recognises,
 * drawn from the icon set the rest of the storefront already uses, so the footer
 * carries the affordance without borrowing anyone's brand.
 *
 * Each one is labelled rather than left as a bare glyph. A generic mark is not
 * self-evident the way a network's is, and an unlabelled row of four icons asks
 * the reader to guess.
 */
const paymentMethods = [
  { Icon: CreditCard, label: "Credit and debit" },
  { Icon: Nfc, label: "Contactless" },
  { Icon: Wallet, label: "Digital wallet" },
  { Icon: Banknote, label: "Bank transfer" },
];

/**
 * The storefront's closing band.
 *
 * Two things a shop's footer does, and one this one has to. It repeats the brand
 * and it names how you would pay - the ordinary furniture whose absence is what
 * made every surface end on a bare grid. The third is the disclosure: a
 * storefront that shows prices, stock and reviews, and then offers payment
 * methods, has to say plainly that none of it charges anything and none of it is
 * real, because everything else on the page is built to be believed.
 */
export function SiteFooter({ inert = false }: { inert?: boolean }) {
  return (
    <footer
      className="site-footer"
      inert={inert || undefined}
      aria-hidden={inert || undefined}
    >
      <div className="site-footer-band">
        <div className="site-footer-brand">
          <Link className="site-footer-mark" href="/" aria-label="Mosaic home">
            <MosaicMark />
            <strong>Mosaic</strong>
          </Link>
          <p>A demonstration storefront for Amazon Aurora PostgreSQL.</p>
        </div>

        <div className="site-footer-payment">
          <span className="site-footer-eyebrow">Payment methods</span>
          <ul aria-label="Payment methods">
            {paymentMethods.map(({ Icon, label }) => (
              <li key={label}>
                <Icon size={15} aria-hidden="true" />
                {label}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="site-footer-legal">
        <p>
          Nothing here charges a card. Products, prices, reviews and availability
          are synthetic data built for this workshop.
        </p>
        <p className="site-footer-stack">
          Amazon Aurora PostgreSQL · pgvector · Amazon Bedrock
        </p>
      </div>
    </footer>
  );
}
