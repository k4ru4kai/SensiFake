"""v0.1 selected-policy replay; no search, models, images or result overwrite."""
import argparse
import json

from verify_recorded_results import verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(verify(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
