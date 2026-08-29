import {
  Check,
  CheckCircle2,
  ChevronLeft,
  CreditCard,
  LockKeyhole,
  Minus,
  PackageCheck,
  Plus,
  RotateCcw,
  ShieldCheck,
  ShoppingBag,
  Trash2,
  Truck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  calculateOrderSummary,
  cartQuantityLimit,
  cartProductImage,
  type DeliveryMethod,
  expressShipping,
  freeShippingThreshold,
  standardShipping,
  useCommerce,
} from "../commerce";
import { formatPrice, leafCategory } from "../format";
import { lockBodyScroll } from "../scrollLock";

type CheckoutStage = "cart" | "delivery" | "payment" | "review" | "complete";

type DeliveryDetails = {
  email: string;
  firstName: string;
  lastName: string;
  address: string;
  city: string;
  state: string;
  postalCode: string;
  shippingMethod: DeliveryMethod;
};

const checkoutSteps: Array<{ stage: CheckoutStage; label: string }> = [
  { stage: "delivery", label: "Delivery" },
  { stage: "payment", label: "Payment" },
  { stage: "review", label: "Review" },
];

function emptyDeliveryDetails(): DeliveryDetails {
  return {
    email: "",
    firstName: "",
    lastName: "",
    address: "",
    city: "",
    state: "",
    postalCode: "",
    shippingMethod: "standard",
  };
}

function OrderTotals({
  summary,
}: {
  summary: ReturnType<typeof calculateOrderSummary>;
}) {
  return (
    <dl className="commerce-totals">
      <div><dt>Subtotal</dt><dd>{formatPrice(summary.subtotal)}</dd></div>
      <div>
        <dt>Shipping</dt>
        <dd>{summary.shipping ? formatPrice(summary.shipping) : "Complimentary"}</dd>
      </div>
      <div><dt>Estimated tax</dt><dd>{formatPrice(summary.tax)}</dd></div>
      <div className="commerce-total"><dt>Total</dt><dd>{formatPrice(summary.total)}</dd></div>
    </dl>
  );
}

export function CommerceDrawer() {
  const {
    lines,
    itemCount,
    isCartOpen,
    closeCart,
    setQuantity,
    removeItem,
    clearCart,
  } = useCommerce();
  const [stage, setStage] = useState<CheckoutStage>("cart");
  const [orderNumber, setOrderNumber] = useState("");
  const drawerRef = useRef<HTMLElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const previousStage = useRef<CheckoutStage>(stage);
  const [delivery, setDelivery] = useState<DeliveryDetails>(emptyDeliveryDetails);
  const summary = useMemo(
    () => calculateOrderSummary(lines, delivery.shippingMethod),
    [delivery.shippingMethod, lines],
  );
  const cartSummary = useMemo(
    () => calculateOrderSummary(lines, "standard"),
    [lines],
  );

  useEffect(() => {
    if (!isCartOpen) return;
    previouslyFocused.current = (
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    );
    const unlockScroll = lockBodyScroll();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopImmediatePropagation();
      closeCart();
    };
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        drawerRef.current?.querySelectorAll<HTMLElement>(
          [
            'button:not([disabled])',
            '[href]',
            'input:not([disabled])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
          ].join(", "),
        ) ?? [],
      ).filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) {
        event.preventDefault();
        drawerRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape, true);
    window.addEventListener("keydown", trapFocus);
    window.requestAnimationFrame(() => {
      drawerRef.current?.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
      )?.focus();
    });
    return () => {
      unlockScroll();
      window.removeEventListener("keydown", closeOnEscape, true);
      window.removeEventListener("keydown", trapFocus);
      if (previouslyFocused.current?.isConnected) {
        previouslyFocused.current.focus();
      }
    };
  }, [closeCart, isCartOpen]);

  useEffect(() => {
    const changed = previousStage.current !== stage;
    previousStage.current = stage;
    if (!isCartOpen || !changed) return;
    const frame = window.requestAnimationFrame(() => headingRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [isCartOpen, stage]);

  useEffect(() => {
    if (isCartOpen) return;
    setStage("cart");
    setOrderNumber("");
    setDelivery(emptyDeliveryDetails());
  }, [isCartOpen]);

  if (!isCartOpen) return null;

  const activeStep = checkoutSteps.findIndex((step) => step.stage === stage);
  const isCheckout = stage !== "cart" && stage !== "complete";

  function updateDelivery(name: keyof DeliveryDetails, value: string) {
    setDelivery((current) => ({ ...current, [name]: value }));
  }

  function finishOrder() {
    setOrderNumber(`MOS-${Date.now().toString().slice(-8)}`);
    clearCart();
    setStage("complete");
  }

  function finishDemo() {
    clearCart();
    setStage("cart");
    setOrderNumber("");
    setDelivery(emptyDeliveryDetails());
    closeCart();
  }

  return (
    <div className="commerce-layer">
      <button
        className="commerce-backdrop"
        type="button"
        aria-label="Close bag"
        onClick={closeCart}
      />
      <aside
        ref={drawerRef}
        className="commerce-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="commerce-drawer-title"
        tabIndex={-1}
      >
        <header className="commerce-drawer-header">
          <div>
            {stage !== "cart" && stage !== "complete" ? (
              <button
                className="commerce-back-button"
                type="button"
                aria-label="Go back"
                onClick={() => {
                  if (stage === "delivery") setStage("cart");
                  if (stage === "payment") setStage("delivery");
                  if (stage === "review") setStage("payment");
                }}
              >
                <ChevronLeft size={19} />
              </button>
            ) : (
              <ShoppingBag size={20} aria-hidden="true" />
            )}
            <span>
              <p className="eyebrow">{isCheckout ? "Secure demo checkout" : "Mosaic shop"}</p>
              <h2 ref={headingRef} id="commerce-drawer-title" tabIndex={-1}>
                {stage === "cart" ? `Your bag (${itemCount})` : null}
                {stage === "delivery" ? "Delivery details" : null}
                {stage === "payment" ? "Payment" : null}
                {stage === "review" ? "Review order" : null}
                {stage === "complete" ? "Order confirmed" : null}
              </h2>
            </span>
          </div>
          <button
            className="commerce-close-button"
            type="button"
            aria-label="Close bag"
            onClick={closeCart}
          >
            <X size={20} />
          </button>
        </header>

        {isCheckout ? (
          <>
            <ol className="checkout-progress" aria-label="Checkout progress">
              {checkoutSteps.map((step, index) => (
                <li
                  key={step.stage}
                  className={
                    index < activeStep
                      ? "complete"
                      : index === activeStep
                        ? "active"
                        : ""
                  }
                >
                  <span>{index < activeStep ? <Check size={12} /> : index + 1}</span>
                  {step.label}
                </li>
              ))}
            </ol>
            <p className="demo-checkout-notice">
              <ShieldCheck size={16} />
              Workshop preview. No payment or order will be processed.
            </p>
          </>
        ) : null}

        {/* key={stage} remounts the body per checkout step so the stage-in
            animation plays on each transition and scroll resets to the top. */}
        <div className="commerce-drawer-body" key={stage}>
          {stage === "cart" ? (
            <>
              {lines.length ? (
                <div className="cart-lines">
                  {lines.map(({ product, quantity }) => {
                    const quantityLimit = cartQuantityLimit(product);
                    return (
                      <article className="cart-line" key={product.product_id}>
                        <img src={cartProductImage(product)} alt="" />
                        <div className="cart-line-copy">
                          <small>{leafCategory(product.category_path)}</small>
                          <strong>{product.model}</strong>
                          <span>{formatPrice(product.price_cents, product.currency)}</span>
                          <div className="cart-line-controls">
                            <div className="quantity-stepper" aria-label={`Quantity for ${product.title}`}>
                              <button
                                type="button"
                                aria-label={`Decrease ${product.title} quantity`}
                                title={quantity === 1 ? "Use Remove to delete this item" : undefined}
                                disabled={quantity === 1}
                                onClick={() => setQuantity(product.product_id, quantity - 1)}
                              >
                                <Minus size={14} />
                              </button>
                              <span aria-live="polite">{quantity}</span>
                              <button
                                type="button"
                                aria-label={`Increase ${product.title} quantity`}
                                title={quantity >= quantityLimit ? "Maximum available quantity reached" : undefined}
                                disabled={quantity >= quantityLimit}
                                onClick={() => setQuantity(product.product_id, quantity + 1)}
                              >
                                <Plus size={14} />
                              </button>
                            </div>
                            <button
                              className="cart-remove"
                              type="button"
                              aria-label={`Remove ${product.title}`}
                              onClick={() => removeItem(product.product_id)}
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </div>
                        <strong>{formatPrice(product.price_cents * quantity, product.currency)}</strong>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-cart">
                  <span><ShoppingBag size={28} /></span>
                  <h3>Your bag is empty</h3>
                  <p>Explore the Mosaic edit and add pieces to begin an order.</p>
                  <button className="commerce-primary-button" type="button" onClick={closeCart}>
                    Continue shopping
                  </button>
                </div>
              )}

              {lines.length ? (
                <>
                  <div className="shipping-progress">
                    <Truck size={17} />
                    <span>
                      {cartSummary.shipping
                        ? `${formatPrice(freeShippingThreshold - cartSummary.subtotal)} away from complimentary shipping`
                        : "Complimentary standard shipping unlocked"}
                    </span>
                    <i
                      style={{
                        width: `${Math.min((cartSummary.subtotal / freeShippingThreshold) * 100, 100)}%`,
                      }}
                    />
                  </div>
                  <OrderTotals summary={cartSummary} />
                </>
              ) : null}
            </>
          ) : null}

          {stage === "delivery" ? (
            <form
              className="checkout-form"
              id="delivery-form"
              onSubmit={(event) => {
                event.preventDefault();
                setStage("payment");
              }}
            >
              <section>
                <h3>Contact</h3>
                <label>
                  Email address
                  <input
                    required
                    type="email"
                    name="email"
                    autoComplete="email"
                    value={delivery.email}
                    onChange={(event) => updateDelivery("email", event.target.value)}
                  />
                </label>
              </section>
              <section>
                <h3>Shipping address</h3>
                <div className="checkout-field-pair">
                  <label>
                    First name
                    <input
                      required
                      name="given-name"
                      autoComplete="given-name"
                      value={delivery.firstName}
                      onChange={(event) => updateDelivery("firstName", event.target.value)}
                    />
                  </label>
                  <label>
                    Last name
                    <input
                      required
                      name="family-name"
                      autoComplete="family-name"
                      value={delivery.lastName}
                      onChange={(event) => updateDelivery("lastName", event.target.value)}
                    />
                  </label>
                </div>
                <label>
                  Address
                  <input
                    required
                    name="street-address"
                    autoComplete="street-address"
                    value={delivery.address}
                    onChange={(event) => updateDelivery("address", event.target.value)}
                  />
                </label>
                <div className="checkout-field-triplet">
                  <label>
                    City
                    <input
                      required
                      name="address-level2"
                      autoComplete="address-level2"
                      value={delivery.city}
                      onChange={(event) => updateDelivery("city", event.target.value)}
                    />
                  </label>
                  <label>
                    State
                    <input
                      required
                      maxLength={2}
                      minLength={2}
                      name="address-level1"
                      pattern="[A-Za-z]{2}"
                      title="Enter a two-letter state code"
                      autoComplete="address-level1"
                      value={delivery.state}
                      onChange={(event) => updateDelivery("state", event.target.value.toUpperCase())}
                    />
                  </label>
                  <label>
                    ZIP
                    <input
                      required
                      inputMode="numeric"
                      maxLength={10}
                      name="postal-code"
                      pattern="[0-9]{5}(-[0-9]{4})?"
                      title="Enter a five-digit ZIP code or ZIP+4"
                      autoComplete="postal-code"
                      value={delivery.postalCode}
                      onChange={(event) => updateDelivery("postalCode", event.target.value)}
                    />
                  </label>
                </div>
              </section>
              <fieldset className="delivery-options">
                <legend>Delivery method</legend>
                <label className={delivery.shippingMethod === "standard" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="delivery"
                    checked={delivery.shippingMethod === "standard"}
                    onChange={() => updateDelivery("shippingMethod", "standard")}
                  />
                  <span><Truck size={18} /><b>Standard</b><small>3-5 business days</small></span>
                  <strong>
                    {summary.subtotal >= freeShippingThreshold
                      ? "Complimentary"
                      : formatPrice(standardShipping)}
                  </strong>
                </label>
                <label className={delivery.shippingMethod === "express" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="delivery"
                    checked={delivery.shippingMethod === "express"}
                    onChange={() => updateDelivery("shippingMethod", "express")}
                  />
                  <span><PackageCheck size={18} /><b>Express</b><small>1-2 business days</small></span>
                  <strong>{formatPrice(expressShipping)}</strong>
                </label>
              </fieldset>
            </form>
          ) : null}

          {stage === "payment" ? (
            <form
              className="checkout-form"
              id="payment-form"
              onSubmit={(event) => {
                event.preventDefault();
                setStage("review");
              }}
            >
              <section>
                <h3>Payment method</h3>
                <p className="checkout-section-note">
                  This checkout uses a demo card. No payment details are requested or stored.
                </p>
                <label className="demo-payment-card">
                  <input type="radio" checked readOnly />
                  <span className="payment-brand"><CreditCard size={20} /></span>
                  <span><b>Demo Visa</b><small>Ending in 4242</small></span>
                  <CheckCircle2 size={18} />
                </label>
                <div className="demo-card-preview" aria-label="Demo Visa ending in 4242">
                  <span><CreditCard size={24} /> Mosaic</span>
                  <strong>•••• &nbsp;•••• &nbsp;•••• &nbsp;4242</strong>
                  <small>DEMO CARD &nbsp;&nbsp; 12/30</small>
                </div>
              </section>
              <p className="checkout-section-note">
                For this workshop preview, the shipping address is also used as the billing address.
              </p>
              <div className="payment-security">
                <LockKeyhole size={17} />
                <span><b>Protected checkout</b><small>No card data leaves this browser.</small></span>
              </div>
            </form>
          ) : null}

          {stage === "review" ? (
            <div className="checkout-review">
              <section>
                <header><h3>Delivery</h3><button type="button" onClick={() => setStage("delivery")}>Edit</button></header>
                <p>
                  <strong>{delivery.firstName} {delivery.lastName}</strong><br />
                  {delivery.address}<br />
                  {delivery.city}, {delivery.state} {delivery.postalCode}<br />
                  {delivery.email}
                </p>
              </section>
              <section>
                <header><h3>Payment</h3><button type="button" onClick={() => setStage("payment")}>Edit</button></header>
                <p><CreditCard size={16} /> Demo Visa ending in 4242</p>
              </section>
              <section>
                <header><h3>Items</h3><span>{itemCount} {itemCount === 1 ? "item" : "items"}</span></header>
                <div className="review-lines">
                  {lines.map(({ product, quantity }) => (
                    <div key={product.product_id}>
                      <img src={cartProductImage(product)} alt="" />
                      <span><strong>{product.model}</strong><small>Qty {quantity}</small></span>
                      <b>{formatPrice(product.price_cents * quantity, product.currency)}</b>
                    </div>
                  ))}
                </div>
              </section>
              <OrderTotals summary={summary} />
            </div>
          ) : null}

          {stage === "complete" ? (
            <div className="checkout-complete">
              <span><Check size={30} /></span>
              <p className="eyebrow">Demo order {orderNumber}</p>
              <h3>Thank you, {delivery.firstName || "shopper"}.</h3>
              <p>
                Your preview order is complete. No payment was charged and no order was submitted.
              </p>
              <div>
                <PackageCheck size={21} />
                <span><b>Estimated delivery</b><small>{delivery.shippingMethod === "express" ? "1-2" : "3-5"} business days</small></span>
              </div>
              <button className="commerce-primary-button" type="button" onClick={finishDemo}>
                Continue shopping
              </button>
            </div>
          ) : null}
        </div>

        {stage !== "complete" && lines.length ? (
          <footer className="commerce-drawer-footer">
            {stage === "cart" ? (
              <>
                <button
                  className="commerce-primary-button"
                  type="button"
                  onClick={() => setStage("delivery")}
                >
                  Checkout <LockKeyhole size={16} />
                </button>
                <div className="commerce-assurance-row">
                  <span><RotateCcw size={15} /> 60-day returns</span>
                  <span><ShieldCheck size={15} /> Secure preview</span>
                </div>
              </>
            ) : null}
            {stage === "delivery" ? (
              <button className="commerce-primary-button" type="submit" form="delivery-form">
                Continue to payment
              </button>
            ) : null}
            {stage === "payment" ? (
              <button className="commerce-primary-button" type="submit" form="payment-form">
                Review order
              </button>
            ) : null}
            {stage === "review" ? (
              <button className="commerce-primary-button" type="button" onClick={finishOrder}>
                Place demo order · {formatPrice(summary.total)}
              </button>
            ) : null}
          </footer>
        ) : null}
      </aside>
    </div>
  );
}
