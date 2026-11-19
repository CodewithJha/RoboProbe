# Font licences

The dashboard ships the fonts below from this directory. Nothing is loaded from a CDN, so the UI renders the same offline
(doc 13 §1.2).

| File                                   | Family / weight   | Licence                                                    | Source                            |
| -------------------------------------- | ----------------- | ---------------------------------------------------------- | --------------------------------- |
| `ibm-plex-sans-latin-400-normal.woff2` | IBM Plex Sans 400 | SIL OFL 1.1 ([`OFL-IBMPlexSans.txt`](OFL-IBMPlexSans.txt)) | `@fontsource/ibm-plex-sans` 5.3.0 |
| `ibm-plex-sans-latin-600-normal.woff2` | IBM Plex Sans 600 | SIL OFL 1.1 ([`OFL-IBMPlexSans.txt`](OFL-IBMPlexSans.txt)) | `@fontsource/ibm-plex-sans` 5.3.0 |
| `ibm-plex-mono-latin-400-normal.woff2` | IBM Plex Mono 400 | SIL OFL 1.1 ([`OFL-IBMPlexMono.txt`](OFL-IBMPlexMono.txt)) | `@fontsource/ibm-plex-mono` 5.3.0 |
| `ibm-plex-mono-latin-600-normal.woff2` | IBM Plex Mono 600 | SIL OFL 1.1 ([`OFL-IBMPlexMono.txt`](OFL-IBMPlexMono.txt)) | `@fontsource/ibm-plex-mono` 5.3.0 |

Only the Latin subset is bundled. To add a weight or subset, copy the matching `files/*.woff2` from the same
`@fontsource` package version, then add an `@font-face` rule in `web/src/styles/fonts.css` and a row here.
