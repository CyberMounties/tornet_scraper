# app/services/rm_container.py
import argparse
import json
import subprocess
import sys
import time


def delete_container(name: str) -> bool:
    """Force-remove *name* with `sudo docker rm -f` and return True on success."""
    try:
        subprocess.run(
            ["sudo", "docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> None:
    """Parse CLI, delete container, print JSON result."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--name", required=True, help="Docker container name")
    args = p.parse_args()

    ok = delete_container(args.name)
    result = {
        "container_name": args.name,
        "success": ok,
        "timestamp": int(time.time()),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

