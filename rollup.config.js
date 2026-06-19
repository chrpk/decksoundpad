import deckyPlugin from "@decky/rollup";

const buildDateTime = new Date().toISOString();

const deckyConfig = deckyPlugin({
  plugins: [buildDateTimePlugin()],
});

export default deckyConfig;

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
  };
}
