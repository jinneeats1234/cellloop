import { Component, type ErrorInfo, type ReactNode } from "react";
import { Icon } from "./ui";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches rendering errors so one broken page shows a recovery screen instead of a blank app.
 * Keyed by route in App.tsx, so navigating elsewhere resets it.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[CellLoop] Page crashed:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="mx-auto max-w-lg py-16">
        <div className="card">
          <div className="mb-3 flex items-center gap-2 text-[var(--danger)]">
            <Icon name="alert" size={18} />
            <h1 className="text-[15px] font-semibold text-[var(--text)]">This page ran into a problem</h1>
          </div>
          <p className="muted text-[13.5px]">
            Something unexpected happened while displaying this page. Your data is safe; nothing was saved or changed.
          </p>
          <details className="mt-3">
            <summary className="subtle cursor-pointer text-[12px]">Technical details</summary>
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-[var(--surface-3)] p-2.5 text-[11px] whitespace-pre-wrap">{error.message}</pre>
          </details>
          <div className="mt-5 flex gap-2">
            <button className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload page
            </button>
            <a className="btn" href="/">
              Go to start
            </a>
          </div>
        </div>
      </div>
    );
  }
}
