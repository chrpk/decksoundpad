# Third-Party Notices

This document summarizes the JavaScript dependency license review for the
current public-release baseline. It is generated from local package metadata
with `corepack pnpm licenses list` and a review of `src/` imports. Regenerate
it with `corepack pnpm run notices:generate` after dependency or import
changes.

DeckSoundpad's own source code is licensed under MIT. The dependency summary
below is provided for release review. License text for production dependencies
and packages directly imported from `src/` is bundled in
`docs/THIRD_PARTY_LICENSES.md`.

## Production Dependencies

| Package | Version | License |
| --- | ---: | --- |
| `@decky/api` | 1.1.3 | LGPL-2.1 |
| `react` | 19.2.7 | MIT |
| `react-icons` | 5.7.0 | MIT |

## LGPL Source Availability

DeckSoundpad distributes Decky LGPL packages only through npm-installed package
contents. No local third-party source modifications are distributed by this
repository. The upstream source locations for LGPL packages used by production
dependencies or imported frontend packages are:

| Package | Version | License | Scope | Upstream source |
| --- | ---: | --- | --- | --- |
| `@decky/api` | 1.1.3 | LGPL-2.1 | Production dependency; Frontend source import | https://github.com/SteamDeckHomebrew/loader-api |
| `@decky/ui` | 4.11.6 | LGPL-2.1 | Frontend source import | https://github.com/SteamDeckHomebrew/decky-frontend-lib |

## Icon Assets

DeckSoundpad imports Font Awesome icons through `react-icons/fa`:

- `FaBell`
- `FaFolderOpen`
- `FaGamepad`
- `FaMicrophone`
- `FaSync`
- `FaTools`
- `FaVolumeUp`

The `react-icons` package license text bundled in
`docs/THIRD_PARTY_LICENSES.md` lists Font Awesome 5 and Font Awesome 6 under
CC BY 4.0. Keep this attribution section current if icon imports change.

## Direct Development Dependencies

The table includes every resolved version associated with a direct development
dependency name. A build plugin can therefore contribute an additional version
of a package that is also declared directly, as `@decky/rollup` does for
TypeScript.

| Package | Version | License |
| --- | ---: | --- |
| `@decky/rollup` | 1.0.2 | BSD-3-Clause |
| `@decky/ui` | 4.11.6 | LGPL-2.1 |
| `@types/react` | 19.2.17 | MIT |
| `@types/react-dom` | 19.2.7 | MIT |
| `react-router` | 8.1.0 | MIT |
| `rollup` | 4.62.2 | MIT |
| `typescript` | 5.9.3 | Apache-2.0 |
| `typescript` | 6.0.3 | Apache-2.0 |

## Transitive License Families Observed

`corepack pnpm licenses list` reported these license families across transitive
dependencies:

- `0BSD`
- `Apache-2.0`
- `BSD-3-Clause`
- `BlueOak-1.0.0`
- `ISC`
- `LGPL-2.1`
- `MIT`

Before each public release, regenerate and verify these notices:

```bash
corepack pnpm run notices:generate
corepack pnpm run validate:licenses
```

The validator checks production packages, packages directly imported from
`src/`, direct development dependencies, and the transitive license-family list.
It also verifies source-availability rows for LGPL packages used by production
dependencies or imported frontend packages. If this file is stale, run
`corepack pnpm run notices:generate` and review whether the ZIP distribution
needs additional notices.
