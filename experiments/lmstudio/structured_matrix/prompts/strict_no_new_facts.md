Return JSON only. Do not use Markdown. Follow the provided JSON schema.

You are cleaning an ASR transcript.

English contract:
- Preserve the original meaning.
- Do not add facts, names, numbers, dates, product claims, decisions, or external context.
- Do not summarize.
- Do not translate.
- Keep technical terms as technical terms; preserve English technical names.
- Fix obvious punctuation and capitalization when the input clearly needs it.
- Remove or soften filler words, repeated self-corrections, and ASR noise only when they do not carry meaning.
- If a phrase is ambiguous, keep it ambiguous instead of inventing details.

Russian contract:
- Сохрани язык исходного текста.
- Не переводи технические термины.
- Не превращай текст в резюме.
- Не добавляй новых фактов.
- Слегка улучши читаемость: пунктуация, капитализация, лишние слова-паразиты.
- Если исправление может изменить смысл, оставь исходную формулировку.

If the schema contains `blocks`, preserve exactly the requested block ids in order. Do not duplicate, omit, or reorder block ids.
