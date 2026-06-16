"""Copy the Cascadeur-side command into the Cascadeur scripts folder.

Usage:
    python install_cascadeur_side.py [--csc "C:\\Program Files\\Cascadeur\\cascadeur.exe"]

Must be run with write permission to the Cascadeur install folder (on Windows this
usually means an elevated/admin shell). Restart Cascadeur afterwards so it picks up
the new command.
"""

import argparse
import os
import shutil
import sys

DEFAULT_CSC = r"C:\Program Files\Cascadeur\cascadeur.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(HERE, "cascadeur_side", "externals")


def commands_dir(csc_exe):
    root = os.path.dirname(csc_exe)
    return os.path.join(root, "resources", "scripts", "python", "commands", "externals")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csc", default=os.environ.get("CASCADEUR_EXE_PATH", DEFAULT_CSC))
    args = parser.parse_args()

    if not os.path.exists(args.csc):
        sys.exit(f"Cascadeur executable not found: {args.csc}")

    dest = commands_dir(args.csc)
    os.makedirs(dest, exist_ok=True)

    copied = []
    for name in os.listdir(SOURCE_DIR):
        if not name.endswith(".py"):
            continue
        shutil.copy2(os.path.join(SOURCE_DIR, name), os.path.join(dest, name))
        copied.append(name)

    print(f"Copied {copied} to:\n  {dest}")
    print("Restart Cascadeur to load the command.")


if __name__ == "__main__":
    main()
