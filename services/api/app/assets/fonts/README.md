# Embedded report font

`NotoSansSC[wght].ttf` is bundled so Chinese PDF reports use an embedded,
cross-platform font instead of a host-only CID/system-font reference.

- Family: Noto Sans SC
- Upstream: `google/fonts`, `ofl/notosanssc/NotoSansSC[wght].ttf`
- Upstream commit object: `fb0637bafbcd804fe32152370a1225990745b4bc`
- Downloaded: 2026-07-13
- SHA-256: `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`
- License: SIL Open Font License 1.1; see `OFL-NotoSansSC.txt`

The font file is unmodified. ReportLab embeds the glyph subset used by each
generated report. Do not replace it with a macOS-only system font: API and
worker containers must render the same PDF on Linux.
