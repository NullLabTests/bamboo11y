import type { ReactNode } from "react";

export function Badge({
  children,
  tone,
  dot = false,
}: {
  children: ReactNode;
  tone: string;
  dot?: boolean;
}) {
  return (
    <span className={`badge badge--${tone}`}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge tone={`severity-${severity}`} dot>
      {severity.toUpperCase()}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={`status-${status}`} dot>
      {status.replaceAll("_", " ")}
    </Badge>
  );
}

export function TierBadge({ tier }: { tier: string }) {
  return <Badge tone={`tier-${tier}`}>{tier}</Badge>;
}
