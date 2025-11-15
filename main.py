import tornado.ioloop
import tornado.web
import tornado.httpclient

import json

from wallet import sign_transaction, private_key_to_address

sk = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80' # test key from anvil

# Counter for JSON-RPC request IDs
_rpc_id_counter = 0

def get_next_rpc_id():
    global _rpc_id_counter
    _rpc_id_counter += 1
    return _rpc_id_counter

class MainHandler(tornado.web.RequestHandler):
    async def get(self):
        calldata = self.get_argument("calldata", None)
        to_address = self.get_argument("to", "0x0000000000000000000000000000000000000000")  # Default to zero address if not provided

        # Derive Ethereum address from private key
        addr = private_key_to_address(sk)

        # Compose and send JSON-RPC request to Anvil for nonce
        http_client = tornado.httpclient.AsyncHTTPClient()
        payload = {
            "jsonrpc": "2.0",
            "id": get_next_rpc_id(),
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

        try:
            nonce = int(json.loads(response.body)["result"], 16)
        except Exception:
            nonce = None
        print(response.body)

        # Get account balance to check if sufficient funds
        balance = None
        try:
            balance_payload = {
                "jsonrpc": "2.0",
                "id": get_next_rpc_id(),
                "method": "eth_getBalance",
                "params": [addr, "latest"]
            }
            balance_request = tornado.httpclient.HTTPRequest(
                url="http://127.0.0.1:8545/",
                method="POST",
                headers=headers,
                body=json.dumps(balance_payload),
            )
            balance_response = await http_client.fetch(balance_request)
            balance = int(json.loads(balance_response.body)["result"], 16)
        except Exception:
            pass

        # Get chain_id from Anvil (default to 31337 if failed)
        chain_id = 31337  # Anvil default
        try:
            chain_id_payload = {
                "jsonrpc": "2.0",
                "id": get_next_rpc_id(),
                "method": "eth_chainId",
                "params": []
            }
            chain_id_request = tornado.httpclient.HTTPRequest(
                url="http://127.0.0.1:8545/",
                method="POST",
                headers=headers,
                body=json.dumps(chain_id_payload),
            )
            chain_id_response = await http_client.fetch(chain_id_request)
            chain_id = int(json.loads(chain_id_response.body)["result"], 16)
        except Exception:
            pass  # Use default chain_id

        # Get gas_price from Anvil (default to 1 gwei for Anvil)
        gas_price = 1000000000  # 1 gwei, reasonable default for Anvil
        try:
            gas_price_payload = {
                "jsonrpc": "2.0",
                "id": get_next_rpc_id(),
                "method": "eth_gasPrice",
                "params": []
            }
            gas_price_request = tornado.httpclient.HTTPRequest(
                url="http://127.0.0.1:8545/",
                method="POST",
                headers=headers,
                body=json.dumps(gas_price_payload),
            )
            gas_price_response = await http_client.fetch(gas_price_request)
            gas_price = int(json.loads(gas_price_response.body)["result"], 16)
        except Exception:
            pass  # Use default gas_price

        # Create and sign transaction if nonce is available and calldata is provided
        tx_hash = None
        calldata_bytes = None
        if calldata:
            # If not valid hex, treat as plain text and convert to hex
            calldata_bytes = calldata.encode('utf-8')
            calldata_hex = '0x' + calldata_bytes.hex()
            
        self.write(f"calldata (original): {calldata} <br>")
        if calldata_hex:
            self.write(f"calldata (hex): {calldata_hex} <br>")
        self.write(f"to: {to_address} <br>")
        self.write(f"address: {addr} <br>")
        if balance is not None:
            self.write(f"balance: {balance} wei ({balance / 10**18:.4f} ETH) <br>")
        self.write(f"nonce: {nonce} <br>")
        self.write(f"chain_id: {chain_id} <br>")
        self.write(f"gas_price: {gas_price} wei ({gas_price / 10**9:.2f} gwei) <br>")


        # Set gas limit (gas_price already fetched above)
        gas_limit = 100000  # Default gas limit

        input('hi')
        # Sign the transaction
        try:
            signed_tx = sign_transaction(
                sk,
                nonce,
                gas_price,
                gas_limit,
                to_address,
                0,  # value in wei
                calldata_bytes,
                chain_id
            )

            # Send signed transaction to Anvil
            send_tx_payload = {
                "jsonrpc": "2.0",
                "id": get_next_rpc_id(),
                "method": "eth_sendRawTransaction",
                "params": [signed_tx]
            }
            send_tx_request = tornado.httpclient.HTTPRequest(
                url="http://127.0.0.1:8545/",
                method="POST",
                headers=headers,
                body=json.dumps(send_tx_payload),
            )
            send_tx_response = await http_client.fetch(send_tx_request)
            tx_result = json.loads(send_tx_response.body)
            if "result" in tx_result:
                tx_hash = tx_result["result"]
            elif "error" in tx_result:
                tx_hash = f"Error: {tx_result['error']}"
        except Exception as e:
            tx_hash = f"Error signing/sending: {str(e)}"

        if tx_hash:
            self.write(f"tx_hash: {tx_hash} <br>")


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
