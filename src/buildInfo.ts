declare const __BUILD_DATETIME__: string | undefined;
declare const __PACKAGE_VERSION__: string | undefined;

const BUILD_DATETIME = formatBuildDateTime(rawBuildDateTime());
const PACKAGE_VERSION = rawPackageVersion();
export const BUILD_METADATA = formatBuildMetadata(
  PACKAGE_VERSION,
  BUILD_DATETIME,
);

function rawBuildDateTime(): string | undefined {
  return typeof __BUILD_DATETIME__ === "string"
    ? __BUILD_DATETIME__
    : undefined;
}

function rawPackageVersion(): string {
  return typeof __PACKAGE_VERSION__ === "string"
    ? __PACKAGE_VERSION__
    : "development";
}

function formatBuildMetadata(version: string, dateTime: string): string {
  if (version === "development") {
    return dateTime;
  }
  return `v${version} | Build ${dateTime}`;
}

function formatBuildDateTime(value: string | undefined): string {
  if (!value) {
    return "development build";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  const seconds = pad(date.getSeconds());
  const offset = formatTimezoneOffset(date);
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} ${offset}`;
}

function formatTimezoneOffset(date: Date): string {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absoluteMinutes = Math.abs(offsetMinutes);
  const hours = pad(Math.floor(absoluteMinutes / 60));
  const minutes = pad(absoluteMinutes % 60);
  return `${sign}${hours}:${minutes}`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
