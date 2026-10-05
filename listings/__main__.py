"""Run one sync cycle by hand:  python -m listings

With LISTINGS_OUTPUT_DIR set it only writes files into that folder (preview);
with GITHUB_TOKEN + GITHUB_REPO set it pushes."""

import logging
import sys

from db import init_db
from listings.publishers import build_publisher
from listings.sync import run_sync


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    publisher = build_publisher()
    if publisher is None:
        print("Nothing to do: set LISTINGS_OUTPUT_DIR (preview) or GITHUB_TOKEN + GITHUB_REPO.")
        return 1
    init_db()
    print(run_sync(publisher).describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
