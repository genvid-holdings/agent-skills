#!/usr/bin/env python3
"""Zero-touch character runner CLI.

    python3 runner/cli.py <group> <cmd> [args]

Groups register their own subcommands; each group module exposes
`register(subparsers)`. Run from any cwd.
"""
import argparse, importlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

GROUPS = ("init", "plate", "mesh", "rig", "studio", "clips", "eval", "record", "biome")
# Group name -> module name, for groups whose module can't share the group's name
# (a module literally named eval.py would shadow the eval() builtin on import).
MODULE_FOR = {"init": "manifest_cli", "eval": "eval_cmd"}

def main(argv=None):
    parser = argparse.ArgumentParser(prog="runner")
    sub = parser.add_subparsers(dest="group", required=True)
    for g in GROUPS:
        try:
            mod = importlib.import_module(MODULE_FOR.get(g, g))
        except ImportError:
            continue
        mod.register(sub)
    args = parser.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main() or 0)
