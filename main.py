from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import json

from wallet import sign_transaction, private_key_to_address

sk = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80' # test key from anvil

# Counter for JSON-RPC request IDs
_rpc_id_counter = 0
_tx_counter = 1

def get_next_rpc_id():
    global _rpc_id_counter
    _rpc_id_counter += 1
    return _rpc_id_counter

def send_json_rpc_request(url, method, params):
    """Send JSON-RPC request and return response body"""
    payload = {
        "jsonrpc": "2.0",
        "id": get_next_rpc_id(),
        "method": method,
        "params": params
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as response:
        return response.read().decode('utf-8')

class MainHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse query parameters
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        calldata = query_params.get("calldata", [None])[0]
        to_address = query_params.get("to", ["0x0000000000000000000000000000000000000000"])[0]

        # Derive Ethereum address from private key
        addr = private_key_to_address(sk)

        # Compose and send JSON-RPC request to Anvil for nonce
        try:
            response_body = send_json_rpc_request(
                "http://127.0.0.1:8545/",
                "eth_getTransactionCount",
                [addr, "latest"]
            )
            response_data = json.loads(response_body)
            nonce = int(response_data["result"], 16) if "result" in response_data else None
            # print(response_body)
        except Exception:
            nonce = None

        # Get account balance to check if sufficient funds
        balance = None
        try:
            balance_response = send_json_rpc_request(
                "http://127.0.0.1:8545/",
                "eth_getBalance",
                [addr, "latest"]
            )
            balance_data = json.loads(balance_response)
            balance = int(balance_data["result"], 16) if "result" in balance_data else None
        except Exception:
            pass

        # Get chain_id from Anvil (default to 31337 if failed)
        chain_id = 31337  # Anvil default
        try:
            chain_id_response = send_json_rpc_request(
                "http://127.0.0.1:8545/",
                "eth_chainId",
                []
            )
            chain_id_data = json.loads(chain_id_response)
            chain_id = int(chain_id_data["result"], 16) if "result" in chain_id_data else chain_id
        except Exception:
            pass  # Use default chain_id

        # Get gas_price from Anvil (default to 1 gwei for Anvil)
        gas_price = 1000000000  # 1 gwei, reasonable default for Anvil
        try:
            gas_price_response = send_json_rpc_request(
                "http://127.0.0.1:8545/",
                "eth_gasPrice",
                []
            )
            gas_price_data = json.loads(gas_price_response)
            gas_price = int(gas_price_data["result"], 16) if "result" in gas_price_data else gas_price
        except Exception:
            pass  # Use default gas_price

        # Create and sign transaction if nonce is available and calldata is provided
        tx_hash = None
        calldata_bytes = None
        calldata_hex = None
        if calldata:
            # If not valid hex, treat as plain text and convert to hex
            calldata_bytes = calldata.encode('utf-8')
            calldata_hex = '0x' + calldata_bytes.hex()

        # Prepare response HTML
        response_parts = []
        global _tx_counter
        tx_counter = _tx_counter
        response_parts.append(f"sign #: {tx_counter} <br>")
        _tx_counter += 1
        response_parts.append(f"calldata (original): {calldata} <br>")
        if calldata_hex:
            response_parts.append(f"calldata (hex): {calldata_hex} <br>")
        response_parts.append(f"to: {to_address} <br>")
        response_parts.append(f"address: {addr} <br>")
        if balance is not None:
            response_parts.append(f"balance: {balance} wei ({balance / 10**18:.4f} ETH) <br>")
        response_parts.append(f"nonce: {nonce} <br>")
        response_parts.append(f"chain_id: {chain_id} <br>")
        response_parts.append(f"gas_price: {gas_price} wei ({gas_price / 10**9:.2f} gwei) <br>")

        # Send response
        response_html = "".join(response_parts)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(response_html.encode('utf-8'))
        self.wfile.write('<br>Wait for confirm in the terminal ... <br>'.encode('utf-8'))

        # Set gas limit (gas_price already fetched above)
        gas_limit = 100000  # Default gas limit

        input(f'proceed #{tx_counter}? y or reject: ')
        # Sign the transaction
        if nonce is not None and calldata_bytes:
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
                send_tx_response = send_json_rpc_request(
                    "http://127.0.0.1:8545/",
                    "eth_sendRawTransaction",
                    [signed_tx]
                )
                tx_result = json.loads(send_tx_response)
                if "result" in tx_result:
                    tx_hash = tx_result["result"]
                    print(f'sent {tx_hash}!')
                elif "error" in tx_result:
                    tx_hash = f"Error: {tx_result['error']}"
            except Exception as e:
                tx_hash = f"Error signing/sending: {str(e)}"

        if tx_hash:
            self.wfile.write(f"tx_hash: {tx_hash} <br>".encode('utf-8'))


    def log_message(self, format, *args):
        # Override to customize logging
        pass

def main():
    port = 5333
    server = HTTPServer(("127.0.0.1", port), MainHandler)
    print(f"Server listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()

if __name__ == "__main__":
    main()
