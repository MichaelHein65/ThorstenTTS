import argparse
import sys

from tts_client import speak


def main() -> int:
    parser = argparse.ArgumentParser(description="Speak text via Piper on a Pi and afplay on macOS")
    parser.add_argument("--host", required=True, help="Pi host (e.g. pi5)")
    parser.add_argument("--user", required=True, help="SSH user (e.g. pi)")
    parser.add_argument("text", help="Text to speak")
    args = parser.parse_args()

    try:
        speak(args.text, args.host, args.user)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
