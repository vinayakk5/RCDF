import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine  # noqa: E402
from migrations import MIGRATIONS, applied_versions, upgrade  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "upgrade":
        ran = upgrade(engine)
        print("Applied: " + (", ".join(ran) if ran else "nothing, database is up to date"))
    elif cmd == "status":
        done = applied_versions(engine)
        for v, n, _ in MIGRATIONS:
            print(f"{'applied' if v in done else 'PENDING'}  {v}  {n}")
    else:
        print("usage: python -m migrations [status|upgrade]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
