# OCDD transient artifact worker

The API can use this worker by setting `OCDD_DOCUMENT_PROCESSOR=celery`. Both
processes must receive the same URL-safe-base64 `OCDD_WORKER_ENVELOPE_KEY`,
which must decode to exactly 32 bytes. Missing or malformed keys fail closed.

Uploads are AES-256-GCM encrypted before entering Valkey through its
Redis-compatible protocol. The worker decrypts
into an opaque mode-0600 temporary file, performs text extraction/OCR, removes
that file in a `finally` block, then encrypts the parsed result before Valkey.
Original filenames, document plaintext, and extracted page text are never
Celery arguments, results, or application log messages in plaintext.

The Celery worker extracts text and page locators from transient user uploads,
computes an integrity hash, and deletes the source after parsing. A periodic
task removes any source left beyond `OCDD_ARTIFACT_TTL_SECONDS`.

Scanned PDFs are rendered with Poppler and OCRed with Tesseract (`eng+chi_sim`
by default). If the tools or language data are unavailable, the result stays
`needs_ocr: true`; an empty extraction is never treated as success. Worker logs
use opaque artifact identifiers and never include extracted text. Set
`OCDD_OCR_ENABLED=false` to disable OCR.
