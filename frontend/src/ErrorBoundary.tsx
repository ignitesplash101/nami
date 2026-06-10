import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  // Injectable for tests; defaults to a full page reload.
  reload?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The one place state can't surface the failure — the tree below is gone.
    console.error("nami workbench crashed:", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    const reload = this.props.reload ?? (() => window.location.reload());
    return (
      <main className="error-boundary-shell">
        <section className="error-boundary-panel" role="alert">
          <p className="eyebrow">nami</p>
          <h2>Something went wrong</h2>
          <p className="muted">
            The workbench hit an unexpected error. Reload to recover — saved scenarios and
            portfolios are unaffected; an unsaved run will need a re-run.
          </p>
          <button type="button" className="primary-button" onClick={reload}>
            Reload workbench
          </button>
        </section>
      </main>
    );
  }
}
