"""Detach Node with only its log handles, so CLI callers can close their output pipes."""

from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    node, directory, port, log_directory = sys.argv[1:]
    logs = Path(log_directory)
    with (logs / f"server-{port}.log").open("wb") as out, (logs / f"server-{port}.err.log").open("wb") as err:
        service = subprocess.Popen(
            [node, "server/start.mjs", "--port", port], cwd=directory,
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    print(service.pid)
