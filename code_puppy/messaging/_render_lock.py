"""Shared lock serializing writes to the interactive display console.

In interactive mode several threads print to the *same* Rich ``Console``
(the queue-listener thread, the MessageBus renderer thread, spinners, and
the streaming handler). ``rich.Console`` is not thread-safe, so concurrent
``print`` calls can interleave/corrupt output. Every writer to the shared
display console acquires this lock around its ``console.print`` calls so
output stays serialized.

It is a re-entrant lock so a writer already holding it (e.g. a helper that
prints a header then delegates to another printing helper) doesn't
self-deadlock.
"""

import threading

CONSOLE_RENDER_LOCK = threading.RLock()
