# app/services/container_status.py
import argparse, json, shutil, subprocess, sys, time


def cmd_exists(executable: str) -> bool:
    """Return True if *executable* is on $PATH."""
    return shutil.which(executable) is not None


def container_running(name: str) -> bool:
    """Return True if container *name* exists and its State.Running is true."""
    try:
        out = subprocess.check_output(
            ["sudo", "docker", "inspect", "-f", "{{.State.Running}}", name],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip().lower()
        return out == "true"
    except subprocess.CalledProcessError:
        return False


def main():
    """Parse CLI, report container status as JSON, exit 0/1 on success/failure."""
    if not cmd_exists("docker"):
        print("ERROR: docker CLI not found.", file=sys.stderr)
        sys.exit(1)

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--name", required=True, help="Docker container name")
    args = p.parse_args()

    running = container_running(args.name)
    result = {
        "container_name": args.name,
        "running": running,
        "timestamp": int(time.time()),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if running else 1)


if __name__ == "__main__":
    main()

