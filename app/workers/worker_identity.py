"""The current process's worker id, shared by runner.py, job_stages.py and
lease.py. Kept in its own tiny module so those three can import it without
any of them having to import *each other* (runner.py is the one that still
needs the others' functions, not the reverse)."""

from __future__ import annotations

import os
import socket
from uuid import uuid4

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"
