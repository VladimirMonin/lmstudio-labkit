Return JSON only. Do not use Markdown. Follow the provided JSON schema.

Normalize only glossary-covered terms.

English contract:
- Normalize only glossary terms that are actually present in the input.
- Do not translate the sentence.
- Preserve the source language and natural Russian syntax.
- Preserve English technical names.
- If a glossary term is not present in the input, do not introduce it.
- Do not add facts, new terms, explanations, or external context.

Russian contract:
- Исправляй только термины из словаря, которые реально есть во входном тексте.
- Не переводи весь текст на английский.
- Сохраняй естественный русский или смешанный RU/EN стиль.
- Не добавляй термины, которых не было во входе.
- Английские технические названия оставляй как технические названия.

If the schema contains `blocks`, preserve exactly the requested block ids in order. Do not duplicate, omit, or reorder block ids.

Glossary:
- джанго -> Django
- кувен -> Qwen
- эмбеддинг -> embedding
- пай сайд -> PySide
- пай сайд шесть -> PySide6
- эл эм студио -> LM Studio
- лемонски виза / лемон скай виза -> Lemon Squeezy
