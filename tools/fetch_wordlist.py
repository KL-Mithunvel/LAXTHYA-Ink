"""Download the English word list the control text is built from.

    python tools/fetch_wordlist.py            # saves to the path in config.yaml -> prompts.word_list
    python tools/fetch_wordlist.py --force    # replace an existing file

The list is first20hours/google-10000-english (no-swears variant): the 10,000 most common
English words in order of frequency, derived from the Google Web Trillion Word Corpus. Its
licence permits educational and personal/research use and does not clearly allow
redistribution, so the file is NOT committed: it goes under the git-ignored data/ folder.
The download is checked against a pinned SHA-256 so a changed file is noticed.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from laxthya_ink.config import load_config, resolve_path  # noqa: E402

BASE = "https://raw.githubusercontent.com/first20hours/google-10000-english/master/"
WORDS = "google-10000-english-no-swears.txt"
LICENSE = "LICENSE.md"
#: checksum of the file this project was built and tested with
WORDS_SHA256 = "d6b3e04f1ac30be6525d41474166c0bff28486ecd8c48dcb0ab9c7c9cc05ed86"
TIMEOUT_S = 30


def fetch(name: str) -> bytes:
    with urllib.request.urlopen(BASE + name, timeout=TIMEOUT_S) as response:      # noqa: S310 - fixed https URL
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="replace the file if it already exists")
    args = parser.parse_args()

    target = resolve_path(load_config()["prompts"]["word_list"])
    if target.exists() and not args.force:
        print(f"already present: {target} (use --force to replace)")
        return 0

    data = fetch(WORDS)
    digest = hashlib.sha256(data).hexdigest()
    if digest != WORDS_SHA256:
        print(f"FAIL: the downloaded file has SHA-256 {digest}, expected {WORDS_SHA256}.\n"
              f"Nothing was saved. The upstream list changed; review it before updating WORDS_SHA256.")
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    (target.parent / "google-10000-english.LICENSE.md").write_bytes(fetch(LICENSE))
    print(f"saved {target} ({len(data)} bytes, SHA-256 verified) and its licence next to it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
