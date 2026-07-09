Return JSON only. Extract a structured document from the public-safe image.

Schema intent:
- document: image type, language, sections and visible elements.
- extracted_data: tables, charts, UI controls, and code entities when present.
- warnings: uncertainty or safety notes; use [] if none.

Complex schema is prepared-only and must not be the first live image run.
Do not identify people. Do not infer private or sensitive attributes.
