# b0x stand for a lockbox for 0x address
# there is a master key and a authenticator
# the master key is loaded sk from encrypted file
# the authenticator approve a sign
# it is used to approve for the signature during the agent chat

import argparse
import sys

def load_key(args):
    print(f"Loading master key from {args.file}...")
    # TODO: Implement loading sk from encrypted file
    pass

def gen_key(args):
    print(f"Generating new private key...")
    # TODO: Implement generating new private key
    pass

def auth_code(args):
    print(f"Generating authenticator QR code...")
    # TODO: Implement generating authenticator QR code
    pass

def run_b0x(args):
    print(f"Starting lockb0x on port {args.port}...")
    # TODO: Implement authenticator service
    pass

def main():
    parser = argparse.ArgumentParser(description="b0x: A lockbox for 0x addresses")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # load subcommand
    load_parser = subparsers.add_parser("load", help="Load private key or mnemonic from prompt")
    load_parser.set_defaults(func=load_key)

    # generate subcommand
    gen_parser = subparsers.add_parser("gen", help="Generate a new private key")
    gen_parser.set_defaults(func=gen_key)

    # auth subcommand
    auth_parser = subparsers.add_parser("auth", help="Generate a authenticator QR code")
    auth_parser.set_defaults(func=auth_code)

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run the lockb0x authenticator service")
    run_parser.add_argument("--port", type=int, default=5333, help="Port to listen on (default: 5333)")
    run_parser.set_defaults(func=run_b0x)


    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
