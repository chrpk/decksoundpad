declare const __BUILD_DATETIME__: string | undefined;

declare global {
  interface Window {
    DECKSOUNDPAD_BUILD_DATETIME?: string;
  }
}

export function getBuildDateTime(): string {
  const rawValue =
    typeof __BUILD_DATETIME__ === "string" ? __BUILD_DATETIME__ : window.DECKSOUNDPAD_BUILD_DATETIME;
  return formatBuildDateTime(rawValue);
}

function formatBuildDateTime(value: string | undefined): string {
  if (!value) {
    return "development build";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())} ${formatTimezoneOffset(date)}`;
}

function formatTimezoneOffset(date: Date): string {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absoluteMinutes = Math.abs(offsetMinutes);
  return `${sign}${pad(Math.floor(absoluteMinutes / 60))}:${pad(absoluteMinutes % 60)}`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
