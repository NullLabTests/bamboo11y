const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const hourFormatter = new Intl.DateTimeFormat(undefined, { hour: "numeric" });

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : dateTimeFormatter.format(date);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : timeFormatter.format(date);
}

export function formatHour(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : hourFormatter.format(date);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${total % 60}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export function formatAge(seconds: number): string {
  return `${formatDuration(seconds)} ago`;
}

export function formatMinutes(value: number): string {
  const rounded = Math.abs(value) < 1 ? value.toFixed(1) : String(Math.round(value));
  return `${rounded} min`;
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function shortFingerprint(value: string, length = 10): string {
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function asSourceLabel(source: string): string {
  if (source === "prometheus") return "Prometheus Alertmanager";
  if (source === "cloudwatch") return "AWS CloudWatch";
  if (source === "open-integration") return "Open Integration";
  return source;
}
