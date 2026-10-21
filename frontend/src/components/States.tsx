import type { ReactNode } from "react";

import type { ApiError } from "../api/client";

export function LoadingState({ label = "Loading operational data" }: { label?: string }) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <div>
        <p className="state__title">{label}</p>
        <p className="state__copy">Reading from the local incident store.</p>
      </div>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <span className="state__glyph" aria-hidden="true">
        !
      </span>
      <div>
        <p className="state__title">Could not load this view</p>
        <p className="state__copy">{error.message}</p>
        {error.hints.length > 0 ? (
          <ul className="state__hints">
            {error.hints.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        ) : null}
        {error.requestId ? (
          <p className="state__meta">
            Request ID <code>{error.requestId}</code>
          </p>
        ) : null}
        {onRetry ? (
          <button type="button" className="button button--secondary" onClick={onRetry}>
            Retry request
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  copy,
  action,
}: {
  title: string;
  copy: string;
  action?: ReactNode;
}) {
  return (
    <div className="state state--empty">
      <span className="state__glyph" aria-hidden="true">
        ◌
      </span>
      <div>
        <p className="state__title">{title}</p>
        <p className="state__copy">{copy}</p>
        {action ? <div className="state__action">{action}</div> : null}
      </div>
    </div>
  );
}
