import re
import shutil
import sys


REPLACEMENT_LENGTH_TEXT = "0.001"
ZERO_LENGTH_PATTERN = re.compile(r'(<geometry\b[^>]*\blength=")0(?:\.0+)?(")')
BACKUP_SUFFIX = ".prepatch.bak"


def patch(path: str) -> None:
    backup_path = path + BACKUP_SUFFIX
    shutil.copy(path, backup_path)
    print(f"Backup saved: {backup_path}")

    with open(path, "r", encoding="utf-8", errors="replace") as xodr_file:
        original_content = xodr_file.read()

    patched_content, patched_count = ZERO_LENGTH_PATTERN.subn(
        rf"\g<1>{REPLACEMENT_LENGTH_TEXT}\g<2>", original_content
    )

    with open(path, "w", encoding="utf-8", errors="replace") as xodr_file:
        xodr_file.write(patched_content)

    print(f"Patched {patched_count} zero-length <geometry> elements to length={REPLACEMENT_LENGTH_TEXT}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <file_path>")
        sys.exit(1)
    
    patch(sys.argv[1])   