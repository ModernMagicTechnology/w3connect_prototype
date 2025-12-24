import argparse
import logging

import multiaddr
import trio

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.network.stream.net_stream import INetStream


logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/w3connect/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def handle_stream(stream: INetStream) -> None:
    try:
        peer_id = stream.muxed_conn.peer_id
        print(f"[server] incoming stream from {peer_id}")
        data = await stream.read(MAX_READ_LEN)
        if data:
            print(f"[server] received: {data.decode(errors='replace')}")
        await stream.write(b"hello from public server")
    except StreamEOF:
        print("[server] stream closed by remote peer")
    except Exception as exc:
        print(f"[server] stream handler error: {exc}")
    finally:
        await stream.close()


async def run(listen_addr: str) -> None:
    host = new_host()
    listen_addrs = [multiaddr.Multiaddr(listen_addr)]

    async with host.run(listen_addrs=listen_addrs):
        host.set_stream_handler(PROTOCOL_ID, handle_stream)

        peer_id = host.get_id().to_string()
        print("[server] peer id:", peer_id, flush=True)
        for addr in listen_addrs:
            print(f"[server] listen addr: {addr}/p2p/{peer_id}", flush=True)

        await trio.sleep_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Public libp2p server example")
    parser.add_argument(
        "--listen-addr",
        default="/ip4/0.0.0.0/tcp/4001",
        help="Multiaddr to listen on",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        trio.run(run, args.listen_addr)
    except KeyboardInterrupt:
        pass
