# b0x stand for a lockbox for 0x address
# there is a master key and a authenticator
# the master key is loaded sk from encrypted file
# the authenticator approve a sign
# it is used to approve for the signature during the agent chat

import argparse
import json
import getpass
import os
import time

import pyotp
import qrcode
import tornado.ioloop
import tornado.web
from eth_account import Account
from web3 import Web3

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Global variables for the service
account = None
totp_secret = None
used_codes = set()
last_api_call_timestamp = time.time() - 30

BASE_RPC = 'https://base-mainnet.infura.io/v3/723b88cdc0f14abca5b7847727a6edbf'
BASE_CHAIN_ID = 8453

BASE_USDC_CONTRACT = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'

BASE_RPC_TESTNET = 'https://base-sepolia.infura.io/v3/723b88cdc0f14abca5b7847727a6edbf'
BASE_CHAIN_ID_TESTNET = 84532

BASE_USDC_CONTRACT_TESTNET = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'


ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]

PUSDC_CONTRACT_BASE = '0x5F40E750B1c5dCe3c55942e35DA0D4Ec83cBd80D'

PUSDC_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_amount", "type": "uint256"}
        ],
        "name": "sendFund",
        "outputs": [],
        "type": "function"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "txNo", "type": "uint256"}
        ],
        "name": "InboxSend",
        "type": "event"
    }
]


def load_key(args):
    filename = args.file
    if not os.path.exists(filename):
        print(f"Error: {filename} not found.")
        return None

    print(f"Loading master key from {filename}...")
    password = getpass.getpass(f"Enter password to decrypt {filename}: ")
    
    try:
        with open(filename, "r") as f:
            key_json = json.load(f)
        
        # Decrypt the private key
        private_key_bytes = Account.decrypt(key_json, password)
        account = Account.from_key(private_key_bytes)
        
        print(f"Success! Private key loaded for address: {account.address}")
        return account, password
    except Exception as e:
        print(f"Error: Failed to decrypt key. Incorrect password? ({e})")
        return None, None

def gen_key(args):
    print(f"Generating new private key...")
    password = getpass.getpass("Enter password to encrypt the private key: ")
    confirm_password = getpass.getpass("Confirm password: ")
    
    if password != confirm_password:
        print("Error: Passwords do not match!")
        return

    # Generate a new account
    account = Account.create()
    
    # Encrypt the private key (uses AES-128-CTR by default in V3 keystore)
    key_json = account.encrypt(password)
    
    # Save to key.json
    filename = "key.json"
    with open(filename, "w") as f:
        json.dump(key_json, f, indent=4)
    
    print(f"Success! Private key generated and saved to {filename}")
    print(f"Public Address: {account.address}")
    print("Please keep your password safe. You will need it to use this key.")

def encrypt_data(data, password):
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(password.encode())
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data.encode(), None)
    return {
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex()
    }

def decrypt_data(encrypted_dict, password):
    salt = bytes.fromhex(encrypted_dict["salt"])
    nonce = bytes.fromhex(encrypted_dict["nonce"])
    ciphertext = bytes.fromhex(encrypted_dict["ciphertext"])
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(password.encode())
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()

def auth_code(args):
    key_filename = "key.json"
    auth_filename = "auth.json"
    
    if not os.path.exists(key_filename):
        print(f"Error: {key_filename} not found. Please run 'gen' first.")
        return

    print(f"To generate authenticator, please verify your password for {key_filename}")
    password = getpass.getpass(f"Enter password: ")
    
    try:
        with open(key_filename, "r") as f:
            key_json = json.load(f)
        # Verify password by trying to decrypt
        Account.decrypt(key_json, password)
        print("Password verified.")
    except Exception as e:
        print(f"Error: Invalid password ({e})")
        return

    # Generate TOTP secret
    secret = pyotp.random_base32()
    address = key_json.get("address", "lockb0x")
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=address, issuer_name="lockb0x")
    
    print("\nScan this QR code with your Google Authenticator app:")
    qr = qrcode.QRCode()
    qr.add_data(uri)
    qr.print_ascii()
    
    print(f"Secret (if QR doesn't work): {secret}")
    
    # Verify
    verify_code = input("\nEnter the code from your app to verify: ")
    totp = pyotp.totp.TOTP(secret)
    if totp.verify(verify_code.replace(" ", "")):
        print("Verification successful!")
        
        # Save to auth.json with the same password
        encrypted_auth = encrypt_data(secret, password)
        with open(auth_filename, "w") as f:
            json.dump(encrypted_auth, f, indent=4)
        print(f"Authenticator secret saved to {auth_filename}")
    else:
        print("Verification failed. Please try again.")


class AddressHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with, content-type")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def options(self):
        self.set_status(204)
        self.finish()

    def get(self):
        global last_api_call_timestamp
        if time.time() - last_api_call_timestamp < 30:
            self.finish({"error": "Too many requests. Please wait a moment."})
            return
        last_api_call_timestamp = time.time()

        self.finish({"address": account.address})

# class VerifyHandler(tornado.web.RequestHandler):
#     def set_default_headers(self):
#         self.set_header("Access-Control-Allow-Origin", "*")
#         self.set_header("Access-Control-Allow-Headers", "x-requested-with, content-type")
#         self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")

#     def options(self):
#         self.set_status(204)
#         self.finish()

#     def get(self):
#         global totp_secret, account
#         if not totp_secret:
#             self.write({"error": "Authenticator not configured on server (auth.json missing)."})
#             return

#         code = self.get_argument("code", None)
#         if not code:
#             self.write({"error": "Verify failed, please provide a one-time password."})
#             return
            
#         totp = pyotp.totp.TOTP(totp_secret)
#         # print(totp.timecode())
#         if totp.verify(code.replace(" ", ""), valid_window=10):
#             self.write({"address": account.address})
#         else:
#             self.write({"error": "Verify failed, please provide a valid one-time password."})


class SendHandler(tornado.web.RequestHandler):
    def get(self):
        global totp_secret
        global account
        global used_codes
        global last_api_call_timestamp
        if time.time() - last_api_call_timestamp < 30:
            self.finish({"error": "Too many requests. Please wait a moment."})
            return
        last_api_call_timestamp = time.time()

        if not totp_secret:
            self.finish({"error": "Authenticator not configured on server (auth.json missing)."})
            return

        code = self.get_argument("code", None)
        if not code:
            self.finish({"error": "Verify failed, please provide a one-time password."})
            return
        code = code.replace(" ", "")
        assert len(code) == 6
        assert code.isdigit()
        if code in used_codes:
            self.finish({"error": "Verify failed, please provide a new one-time password. The code has already been used."})
            return

        token = self.get_argument("token", None)
        if not token:
            self.finish({"error": "Token not provided."})
            return
        if token.upper() not in ["ETH", "USDC"]:
            self.finish({"error": "Token not supported. Currently only ETH and USDC are supported."})
            return

        to_address = self.get_argument("to_address", None)
        if not to_address:
            self.finish({"error": "To address not provided."})
            return
        if not to_address.startswith("0x") and len(to_address) != 42:
            self.finish({"error": "To address is not valid. The address must start with 0x and be 42 characters long."})
            return

        amount = self.get_argument("amount", None)
        if not amount:
            self.finish({"error": "Amount not provided."})
            return
        if float(amount) <= 0:
            self.finish({"error": "Amount must be greater than 0."})
            return

        chain = self.get_argument("chain", None)
        if not chain:
            self.finish({"error": "Chain not provided."})
            return
        if chain not in ["base"]:
            self.finish({"error": "Chain not supported. Currently only base is supported."})
            return


        totp = pyotp.totp.TOTP(totp_secret)
        if not totp.verify(code, valid_window=10):
            self.finish({"error": "Verify failed, please provide a valid one-time password."})
            return
        used_codes.add(code)

        print(f"Sending {amount} {token} to {to_address} on {chain}")

        rpc_url = BASE_RPC
        if not rpc_url:
            self.finish({"error": f"Chain {chain} not supported for RPC."})
            return

        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            self.finish({"error": "Failed to connect to blockchain RPC."})
            return

        try:
            nonce = w3.eth.get_transaction_count(account.address)
            gas_price = w3.eth.gas_price

            if token == "ETH":
                tx = {
                    'nonce': nonce,
                    'to': to_address,
                    'value': w3.to_wei(amount, 'ether'),
                    'gas': 21000,
                    'gasPrice': gas_price,
                    'chainId': BASE_CHAIN_ID
                }
            elif token == "USDC":
                usdc_amount = int(float(amount) * 10**6)
                contract_address = BASE_USDC_CONTRACT
                usdc_contract = w3.eth.contract(address=contract_address, abi=ERC20_ABI)
                
                tx = usdc_contract.functions.transfer(to_address, usdc_amount).build_transaction({
                        'chainId': BASE_CHAIN_ID,
                        'gas': 100000,
                        'gasPrice': gas_price,
                        'nonce': nonce,
                    })
            else:
                self.finish({"error": f"Token {token} not supported."})
                return

            signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.finish({
                "status": "success",
                "tx_hash": tx_hash.hex(),
                "message": f"Sent {amount} {token} to {to_address}"
            })

        except Exception as e:
            self.finish({"error": f"Failed to send transaction: {str(e)}"})


class Pay2EmailHandler(tornado.web.RequestHandler):
    def get(self):
        global totp_secret
        global account
        global used_codes
        global last_api_call_timestamp
        if time.time() - last_api_call_timestamp < 0:
            self.finish({"error": "Too many requests. Please wait a moment."})
            return
        last_api_call_timestamp = time.time()

        if not totp_secret:
            self.finish({"error": "Authenticator not configured on server (auth.json missing)."})
            return

        code = self.get_argument("code", None)
        if not code:
            self.finish({"error": "Verify failed, please provide a one-time password."})
            return
        code = code.replace(" ", "")
        assert len(code) == 6
        assert code.isdigit()
        if code in used_codes:
            self.finish({"error": "Verify failed, please provide a new one-time password. The code has already been used."})
            return

        token = self.get_argument("token", None)
        if not token:
            self.finish({"error": "Token not provided."})
            return
        if token.upper() not in ["USDC"]:
            self.finish({"error": "Token not supported. Currently only USDC is supported."})
            return

        # to_address = self.get_argument("to_address", None)
        # if not to_address:
        #     self.finish({"error": "To address not provided."})
        #     return
        # if not to_address.startswith("0x") and len(to_address) != 42:
        #     self.finish({"error": "To address is not valid. The address must start with 0x and be 42 characters long."})
        #     return

        amount = self.get_argument("amount", None)
        if not amount:
            self.finish({"error": "Amount not provided."})
            return
        if float(amount) <= 0:
            self.finish({"error": "Amount must be greater than 0."})
            return

        chain = self.get_argument("chain", None)
        if not chain:
            self.finish({"error": "Chain not provided."})
            return
        if chain not in ["base"]:
            self.finish({"error": "Chain not supported. Currently only base is supported."})
            return


        totp = pyotp.totp.TOTP(totp_secret)
        if not totp.verify(code, valid_window=10):
            self.finish({"error": "Verify failed, please provide a valid one-time password."})
            return
        used_codes.add(code)

        print(f"Pay2Email {amount} {token} on {chain}")

        rpc_url = BASE_RPC
        if not rpc_url:
            self.finish({"error": f"Chain {chain} not supported for RPC."})
            return

        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            self.finish({"error": "Failed to connect to blockchain RPC."})
            return

        if token.upper() != "USDC":
            self.finish({"error": f"Token {token.upper()} not supported."})
            return

        usdc_amount = int(float(amount) * 10**6)
        contract_address = BASE_USDC_CONTRACT
        usdc_contract = w3.eth.contract(address=contract_address, abi=ERC20_ABI)
        pusdc_contract = w3.eth.contract(address=PUSDC_CONTRACT_BASE, abi=PUSDC_ABI)

        sleep = 2
        while True:
            try:
                nonce = w3.eth.get_transaction_count(account.address)
                gas_price = w3.eth.gas_price
                tx1 = usdc_contract.functions.approve(PUSDC_CONTRACT_BASE, usdc_amount).build_transaction({
                        'from': account.address,
                        'chainId': BASE_CHAIN_ID,
                        'gas': 100000,
                        'gasPrice': gas_price,
                        'nonce': nonce,
                    })
                print('tx1 approve', tx1)
                signed_tx1 = w3.eth.account.sign_transaction(tx1, private_key=account.key)
                tx_hash1 = w3.eth.send_raw_transaction(signed_tx1.raw_transaction)
                print('tx_hash1', tx_hash1.hex())
                time.sleep(2)
                break

            except Exception as e:
                print(f"Failed to send tx1: {e}")
                sleep = sleep * 2
                time.sleep(sleep)
                continue

        sleep = 2
        while True:
            try:
                nonce = w3.eth.get_transaction_count(account.address)
                gas_price = w3.eth.gas_price
                tx2 = pusdc_contract.functions.sendFund(usdc_amount).build_transaction({
                        'from': account.address,
                        'chainId': BASE_CHAIN_ID,
                        'gas': 1000000,
                        'gasPrice': gas_price,
                        'nonce': nonce,
                    })
                print('tx2 sendFund', tx2)
                signed_tx2 = w3.eth.account.sign_transaction(tx2, private_key=account.key)
                tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.raw_transaction)
                print('tx_hash2', tx_hash2.hex())
                time.sleep(2)
                break

            except Exception as e:
                print(f"Failed to send tx2: {e}")
                sleep = sleep * 2
                time.sleep(sleep)
                continue
                
        sleep = 2
        while True:
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash2)
                print(receipt)

                inbox_send_event_signature = w3.keccak(text="InboxSend(uint256)").hex()
                for log in receipt['logs']:
                    if log['topics'] and log['topics'][0].hex() == inbox_send_event_signature:
                        parsed_log = pusdc_contract.events.InboxSend().process_log(log)
                        print(f"Parsed InboxSend event from {log['address']}: {parsed_log.args}")
                        tx_no = parsed_log.args.txNo
                        break
                break

            except Exception as e:
                print(f"Failed to get receipt: {e}")
                sleep = sleep * 2
                time.sleep(sleep)
                continue

        print('tx_no', tx_no)

        self.finish({
            "status": "success",
            "approve_txhash": tx_hash1.hex(),
            "sendFund_txhash": tx_hash2.hex(),
            "txNo": tx_no,
            "message": f"Sent {amount} {token.upper()} to PUSDC in txNo {tx_no}"
        })

        # except Exception as e:
        #     self.finish({"error": f"Failed to send transaction: {str(e)}"})

app = tornado.web.Application([
    (r"/address", AddressHandler),
    # (r"/verify", VerifyHandler),
    (r"/send", SendHandler),
    (r"/pay2email", Pay2EmailHandler),
])

def run_b0x(args):
    global account, totp_secret
    account, password = load_key(args)
    if not account:
        return

    # Load TOTP secret if auth.json exists
    auth_filename = "auth.json"
    if os.path.exists(auth_filename):
        try:
            with open(auth_filename, "r") as f:
                encrypted_auth = json.load(f)
            totp_secret = decrypt_data(encrypted_auth, password)
            print("Authenticator secret loaded.")
        except Exception as e:
            print(f"Warning: Failed to load authenticator secret: {e}")

    print(f"Starting lockb0x on port {args.port}...")
    app.listen(args.port)
    tornado.ioloop.IOLoop.current().start()

def main():
    parser = argparse.ArgumentParser(description="b0x: A lockbox for 0x addresses")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # load subcommand
    load_parser = subparsers.add_parser("load", help="Load private key from encrypted file")
    load_parser.add_argument("--file", type=str, default="key.json", help="Path to the encrypted key file (default: key.json)")
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
    run_parser.add_argument("--file", type=str, default="key.json", help="Path to the encrypted key file (default: key.json)")
    run_parser.set_defaults(func=run_b0x)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        args.func = run_b0x
        args.file = "key.json"
        args.port = 5333
        run_b0x(args)

if __name__ == "__main__":
    main()
