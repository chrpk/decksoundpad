#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="DeckSoundpad"
VERSION="$(node -p "require('${ROOT_DIR}/package.json').version")"
OUT_DIR="${ROOT_DIR}/out/${NAME}"
ZIP_PATH="${ROOT_DIR}/out/${NAME}-v${VERSION}.zip"

rm -rf "${OUT_DIR}" "${ZIP_PATH}"
mkdir -p "${OUT_DIR}"

cp "${ROOT_DIR}/plugin.json" "${OUT_DIR}/"
cp "${ROOT_DIR}/package.json" "${OUT_DIR}/"
cp "${ROOT_DIR}/main.py" "${OUT_DIR}/"
cp "${ROOT_DIR}/README.md" "${OUT_DIR}/"
cp "${ROOT_DIR}/LICENSE" "${OUT_DIR}/"
if [[ -d "${ROOT_DIR}/assets" ]]; then
  cp -R "${ROOT_DIR}/assets" "${OUT_DIR}/"
fi
cp -R "${ROOT_DIR}/defaults" "${OUT_DIR}/"
cp -R "${ROOT_DIR}/backend" "${OUT_DIR}/"
cp -R "${ROOT_DIR}/web" "${OUT_DIR}/"
cp -R "${ROOT_DIR}/scripts" "${OUT_DIR}/"
if [[ -d "${ROOT_DIR}/docs" ]]; then
  cp -R "${ROOT_DIR}/docs" "${OUT_DIR}/"
fi
rm -rf "${OUT_DIR}/backend/tests"
rm -rf "${OUT_DIR}/web/src"
rm -f "${OUT_DIR}/web/index.html"
find "${OUT_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${OUT_DIR}" -type f -name "*.pyc" -delete
find "${OUT_DIR}" -type f -name ".DS_Store" -delete

if [[ -d "${ROOT_DIR}/dist" ]]; then
  cp -R "${ROOT_DIR}/dist" "${OUT_DIR}/"
  find "${OUT_DIR}/dist" -type f -name "*.map" -delete
  find "${OUT_DIR}/dist" -type f -name "*.js" -exec perl -0pi -e 's/\n\/\/# sourceMappingURL=.*?\.map\s*$//s' {} +
else
  mkdir -p "${OUT_DIR}/dist"
  echo "dist/index.js missing; run pnpm run build before release packaging" >&2
fi

(
  cd "${ROOT_DIR}/out"
  zip -qr "$(basename "${ZIP_PATH}")" "${NAME}"
)

echo "${ZIP_PATH}"
