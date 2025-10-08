from __future__ import annotations

SCHEMA_VERSION: str = '1'

# Redis Streams
STREAM_TASKS: str = 'dl:tasks'
STREAM_DONE: str = 'dl:done'
STREAM_FAILED: str = 'dl:failed'

# Consumer Groups
GROUP_WORKERS: str = 'dl:workers'
GROUP_BOT: str = 'bot'

# Stream trimming (soft operational limit)
STREAM_MAXLEN: int = 5000
