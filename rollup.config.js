import fs from "node:fs";
import deckyPlugin from "@decky/rollup";

const buildDateTime = new Date().toISOString();
const packageVersion = JSON.parse(fs.readFileSync(new URL("./package.json", import.meta.url), "utf8")).version;

const deckyConfig = deckyPlugin({
  plugins: [buildMetadataPlugin()],
});

export default deckyConfig;

function buildMetadataPlugin() {
  return {
    name: "decksoundpad-build-metadata",
    renderChunk(code) {
      return code.includes("__BUILD_DATETIME__") || code.includes("__PACKAGE_VERSION__")
        ? {
            code: code
              .replaceAll("__BUILD_DATETIME__", JSON.stringify(buildDateTime))
              .replaceAll("__PACKAGE_VERSION__", JSON.stringify(packageVersion)),
            map: null,
          }
        : null;
    },
  };
}
