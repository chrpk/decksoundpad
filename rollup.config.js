import { readFileSync, writeFileSync } from "fs";
import deckyPlugin from "@decky/rollup";

const buildDateTime = new Date().toISOString();
const webDistIndexUrl = new URL("./web/dist/index.html", import.meta.url);
const webBuildDateTimePattern = /window\.DECKSOUNDPAD_BUILD_DATETIME = "[^"]*";/;

export default deckyPlugin({
  plugins: [buildDateTimePlugin()],
});

function buildDateTimePlugin() {
  return {
    name: "decksoundpad-build-datetime",
    renderChunk(code) {
      return code.includes("__BUILD_DATETIME__")
        ? {
            code: code.replaceAll("__BUILD_DATETIME__", JSON.stringify(buildDateTime)),
            map: null,
          }
        : null;
    },
    writeBundle() {
      try {
        const html = readFileSync(webDistIndexUrl, "utf8");
        const nextHtml = html.replace(
          webBuildDateTimePattern,
          `window.DECKSOUNDPAD_BUILD_DATETIME = ${JSON.stringify(buildDateTime)};`,
        );
        if (nextHtml !== html) {
          writeFileSync(webDistIndexUrl, nextHtml);
        }
      } catch (caught) {
        this.warn(`Unable to stamp web build datetime: ${caught instanceof Error ? caught.message : caught}`);
      }
    },
  };
}
