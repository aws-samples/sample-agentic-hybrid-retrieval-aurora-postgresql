import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * The last stop before a white page.
 *
 * Every route is a `lazy()` chunk, so a dropped connection part-way through a
 * navigation rejects the import, and React unmounts the whole tree for that as
 * readily as for a render throw. Without a boundary the participant gets a blank
 * document and an error only in the console, which on conference wifi is the
 * difference between "one surface is broken" and "the app is dead".
 *
 * A class component because that is still the only way to catch a render error;
 * there is no hook equivalent.
 */
export class RouteErrorBoundary extends Component<
  { children: ReactNode },
  { message: string }
> {
  state = { message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      message: error instanceof Error ? error.message : "Mosaic hit an unexpected error",
    };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    // Keeps the component stack in the console for whoever is debugging, since
    // the visible message deliberately stays short.
    console.error("Mosaic surface failed to render", error, info.componentStack);
  }

  render() {
    if (!this.state.message) return this.props.children;
    return (
      <div className="route-error" role="alert">
        <h1>This surface did not load.</h1>
        <p>{this.state.message}</p>
        <p className="route-error-hint">
          A reload usually clears it. The API and the catalog are unaffected.
        </p>
        <button type="button" onClick={() => window.location.reload()}>
          Reload Mosaic
        </button>
      </div>
    );
  }
}
