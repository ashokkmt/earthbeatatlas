import argparse

from nasa_explorer.processing.jobs import run_once, run_worker

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the bounded NISAR processing worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5)
    args = parser.parse_args()
    if args.once:
        run_once()
    else:
        run_worker(max(1, args.poll_seconds))
