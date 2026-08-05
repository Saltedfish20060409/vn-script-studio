# NovelMaster reference

Cloned for adaptation: https://github.com/necolo007/NovelMaster (MIT)

Only the **chapter batch memory** idea was ported into this backend:

- Grouping chapters by span (`chapter_memory.py` algorithm)
- Continuity / spine / summaries structure
- Stored in PostgreSQL (`chapter_memory_archives` + `chapter_memory_slices`) instead of markdown folders

The NovelMaster skill pack / web viewer was **not** vendored wholesale.
Local clone used during port: `D:\Projects\NovelMaster-ref` (optional reference).
