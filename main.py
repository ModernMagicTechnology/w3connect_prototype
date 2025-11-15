import tornado.ioloop
import tornado.web
import tornado.httpclient

import json

# Derive ETH address from sk
from pyecdsa import _scalar_mult, G, P
from pykeccak import Keccak256

sk = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80' # test key from anvil

class MainHandler(tornado.web.RequestHandler):
    async def get(self):
        calldata = self.get_argument("calldata", None)

        priv_int = int(sk, 16) if sk.startswith("0x") else int(sk, 16)
        pub_pt = _scalar_mult(priv_int, G)
        pub_x = pub_pt[0]
        pub_y = pub_pt[1]
        pubkey_bytes = b'\x04' + pub_x.to_bytes(32, 'big') + pub_y.to_bytes(32, 'big')
        hasher = Keccak256()
        hasher.update(pubkey_bytes[1:])
        addr = '0x' + hasher.digest()[-20:].hex()

        # Compose and send JSON-RPC request to Anvil for nonce

        http_client = tornado.httpclient.AsyncHTTPClient()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionCount",
            "params": [addr, "latest"]
        }
        headers = {"Content-type": "application/json"}
        request = tornado.httpclient.HTTPRequest(
            url="http://127.0.0.1:8545/",
            method="POST",
            headers=headers,
            body=json.dumps(payload),
        )
        response = await http_client.fetch(request)
        response.body

        try:
            nonce = int(json.loads(response.body)["result"], 16)
        except Exception:
            nonce = None


        self.write(f"{calldata} <br>")
        self.write(f"{addr} <br>")
        self.write(f"{nonce} <br>")


def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
    ], debug=True)

def main():
    app = make_app()
    port = 8888
    app.listen(port)
    print(f"Tornado server listening on http://127.0.0.1:{port}")
    tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
