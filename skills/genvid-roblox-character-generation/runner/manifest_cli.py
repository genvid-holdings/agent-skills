import manifest

def register(sub):
    p = sub.add_parser("init", help="create out/<name>/manifest.json")
    p.add_argument("--name", required=True)
    p.add_argument("--project", type=int, required=True)
    p.add_argument("--height", type=float, required=True, help="target height in studs")
    p.add_argument("--vendor", default=None,
                   help="optional hint: the provider you expect to use; recorded, never enforced")
    p.add_argument("--out", required=True)
    p.add_argument("--assignee", help="email to claim the assetImage task for at every "
                    "downstream bind stage; required before any claim-emitting stage runs, "
                    "never defaults to 'me' (that resolves to the agent's own MCP session, "
                    "not the human reviewer)")
    p.add_argument("--production-title", required=True, help="the production's own title; written "
                    "verbatim into the description of every asset this chain creates")
    p.set_defaults(func=run)

def run(args):
    m = manifest.new(args.name, args.project, args.height, args.vendor, args.out,
                     assignee=args.assignee, production_title=args.production_title)
    print("wrote", manifest.save(m))
