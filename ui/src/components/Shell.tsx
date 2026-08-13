import { ReactNode } from "react";
import { useLocation } from "wouter";
import { CommerceDrawer } from "./CommerceDrawer";
import { SiteHeader } from "./SiteHeader";

/**
 * Storefront chrome. The reference boards read as a catalog first and an
 * instrument second, so shopper navigation sits in one header on every surface
 * and the landing only changes what is under it.
 */
export function Shell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const pathname = location.split("?")[0];
  const isLanding = pathname === "/" || pathname === "/discover";

  return (
    <div className={isLanding ? "app-shell landing-shell" : "app-shell"}>
      <SiteHeader />
      <main className={isLanding ? "landing-main" : undefined}>{children}</main>
      <CommerceDrawer />
    </div>
  );
}
