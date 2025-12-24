import argparse
import logging

import multiaddr
import trio

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.peer.peerinfo import info_from_p2p_addr


logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/w3connect/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def run(server_addr: str, message: str) -> None:
    host = new_host()

    async with host.run(listen_addrs=[]):
        maddr = multiaddr.Multiaddr(server_addr)
        peer_info = info_from_p2p_addr(maddr)
        await host.connect(peer_info)

        stream = await host.new_stream(peer_info.peer_id, [PROTOCOL_ID])
        try:
            await stream.write(message.encode())
            data = await stream.read(MAX_READ_LEN)
            if data:
                print(f"[client] received: {data.decode(errors='replace')}")
        except StreamEOF:
            print("[client] stream closed by remote peer")
        except Exception as exc:
            print(f"[client] stream error: {exc}")
        finally:
            await stream.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Private libp2p client example")
    parser.add_argument(
        "--server-addr",
        required=True,
        help="Server multiaddr, e.g. /ip4/1.2.3.4/tcp/4001/p2p/PEERID",
    )
    parser.add_argument("--message", default="hello from private client")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        trio.run(run, args.server_addr, args.message)
    except KeyboardInterrupt:
        pass
