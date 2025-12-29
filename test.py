import asyncio
import threading
import json
import secrets

import tornado.ioloop
import tornado.platform.asyncio
import tornado.web

from pykeccak import Keccak256
from wallet import private_key_to_address

CHAIN_ID_HEX = "0x7a69"  # 31337
_pending_counter = 1
pending_sign_requests = []
pending_lock = threading.Lock()

accounts = []
accounts_lock = threading.Lock()
default_account_index = None
mnemonic_groups = []
with open("bip39_english.txt", "r", encoding="utf-8") as f:
    MNEMONIC_WORDS = [word.strip() for word in f.readlines() if word.strip()]


def _create_mnemonic(num_words=12):
    return " ".join(secrets.choice(MNEMONIC_WORDS) for _ in range(num_words))

def _normalize_hex_key(value):
    if value.startswith("0x"):
        value = value[2:]
    return value.lower()

def _derive_private_key_from_mnemonic(mnemonic, account_index):
    hasher = Keccak256()
    hasher.update(f"{mnemonic}|{account_index}".encode("utf-8"))
    return "0x" + hasher.digest().hex()

def _add_account_from_private_key(priv_key_hex, source, account_type="private_key", mnemonic_group=None, mnemonic_index=None):
    global default_account_index
    priv_key_hex = "0x" + _normalize_hex_key(priv_key_hex)
    address = private_key_to_address(priv_key_hex)
    with accounts_lock:
        for existing in accounts:
            if existing["address"] == address:
                return address, False
        accounts.append(
            {
                "address": address,
                "private_key": priv_key_hex,
                "source": source,
                "type": account_type,
                "mnemonic_group": mnemonic_group,
                "mnemonic_index": mnemonic_index,
            }
        )
        if default_account_index is None:
            default_account_index = 0
    return address, True

def _add_mnemonic_group(mnemonic):
    with accounts_lock:
        mnemonic_groups.append({"mnemonic": mnemonic, "next_index": 1})
        return len(mnemonic_groups)

def _add_account_from_mnemonic_group(group_id):
    if group_id < 1 or group_id > len(mnemonic_groups):
        raise ValueError("Invalid mnemonic group")
    group = mnemonic_groups[group_id - 1]
    account_index = group["next_index"]
    priv_key = _derive_private_key_from_mnemonic(group["mnemonic"], account_index)
    address, added = _add_account_from_private_key(
        priv_key,
        f"mnemonic {group_id}.{account_index}",
        account_type="mnemonic",
        mnemonic_group=group_id,
        mnemonic_index=account_index,
    )
    if added:
        group["next_index"] += 1
    return address, added, account_index

def _format_account_label(entry, fallback_index):
    if entry.get("type") == "mnemonic":
        group_id = entry.get("mnemonic_group")
        account_index = entry.get("mnemonic_index")
        if group_id is not None and account_index is not None:
            return f"{group_id}.{account_index}"
    return str(fallback_index)

def _find_account_index_from_selector(selector):
    if "." in selector:
        parts = selector.split(".", 1)
        if len(parts) != 2:
            return None
        if not parts[0].isdigit() or not parts[1].isdigit():
            return None
        group_id = int(parts[0])
        account_index = int(parts[1])
        for idx, entry in enumerate(accounts):
            if (
                entry.get("type") == "mnemonic"
                and entry.get("mnemonic_group") == group_id
                and entry.get("mnemonic_index") == account_index
            ):
                return idx
        return None
    if selector.isdigit():
        return int(selector)
    return None

def _get_accounts_ordered():
    with accounts_lock:
        if not accounts:
            return []
        if default_account_index is None:
            return [entry["address"] for entry in accounts]
        default_entry = accounts[default_account_index]
        others = [entry["address"] for idx, entry in enumerate(accounts) if idx != default_account_index]
        return [default_entry["address"]] + others

class MainHandler(tornado.web.RequestHandler):
    # def get(self):
    #     print(f"Received GET request from {self.request.remote_ip}")
    #     print(f"Headers: {self.request.headers}")
    #     print(f"Arguments: {self.request.arguments}")
    #     self.write("Hello, this is a GET response from Tornado server.")

    def post(self):
        # Log POST request info
        # print(f"Received POST request from {self.request.remote_ip}")
        # print(f"Headers: {self.request.headers}")
        print(f"Body: {self.request.body}")
        # print(f"Arguments: {self.request.arguments}")
        body = self.request.body
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        jsonrpc_req = json.loads(body)
        result = {"jsonrpc": "2.0", "id": jsonrpc_req['id'], "result": []}
        if jsonrpc_req['method'] == 'eth_accounts':
            result["result"] = _get_accounts_ordered()
        elif jsonrpc_req['method'] == 'eth_requestAccounts':
            result["result"] = _get_accounts_ordered()
        elif jsonrpc_req['method'] == 'eth_chainId':
            result["result"] = CHAIN_ID_HEX
        elif jsonrpc_req['method'] in ('eth_sendTransaction', 'eth_signTransaction'):
            params = jsonrpc_req.get("params") or []
            tx = params[0] if params else {}
            global _pending_counter
            with pending_lock:
                pending_sign_requests.append(
                    {
                        "pending_id": _pending_counter,
                        "method": jsonrpc_req['method'],
                        "tx": tx,
                    }
                )
                _pending_counter += 1
            result["result"] = "0x" + "0" * 64
        else:
            print(jsonrpc_req['method'])
        self.set_header("Content-Type", "application/json")
        self.write(tornado.escape.json_encode(result))

def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
    ])

def start_server_in_thread(port):
    ready = threading.Event()
    state = {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tornado.platform.asyncio.AsyncIOMainLoop().install()
        app = make_app()
        app.listen(port)
        ioloop = tornado.ioloop.IOLoop.current()
        state["ioloop"] = ioloop
        ready.set()
        print(f"Tornado server starting on http://127.0.0.1:{port}/")
        ioloop.start()
        loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait()
    return thread, state["ioloop"]


def cli_loop(ioloop):
    global default_account_index
    print("Menu:")
    print("1) Import private key")
    print("2) Import mnemonic")
    print("3) Create mnemonic")
    print("4) Add mnemonic account")
    print("5) List accounts")
    print("6) Set default account")
    print("7) List pending sign requests")
    print("8) Quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("8", "quit", "exit"):
            break
        if line == "1":
            priv_key = input("Private key hex: ").strip()
            if not priv_key:
                print("No private key provided.")
                continue
            try:
                address, added = _add_account_from_private_key(priv_key, "private_key")
            except Exception as exc:
                print(f"Invalid private key: {exc}")
                continue
            if added:
                print(f"Imported account: {address}")
            else:
                print(f"Account already exists: {address}")
        elif line == "2":
            mnemonic = input("Mnemonic: ").strip()
            if not mnemonic:
                print("No mnemonic provided.")
                continue
            group_id = _add_mnemonic_group(mnemonic)
            address, added, account_index = _add_account_from_mnemonic_group(group_id)
            if added:
                print(f"Imported account: {address} (mnemonic {group_id}.{account_index})")
            else:
                print(f"Account already exists: {address}")
        elif line == "3":
            mnemonic = _create_mnemonic()
            print(f"Created mnemonic: {mnemonic}")
            group_id = _add_mnemonic_group(mnemonic)
            address, added, account_index = _add_account_from_mnemonic_group(group_id)
            if added:
                print(f"Imported account: {address} (mnemonic {group_id}.{account_index})")
            else:
                print(f"Account already exists: {address}")
        elif line == "4":
            if not mnemonic_groups:
                print("No mnemonic groups. Import a mnemonic first.")
                continue
            for idx, group in enumerate(mnemonic_groups, start=1):
                print(f"{idx}: mnemonic group (next index {group['next_index']})")
            choice = input("Select mnemonic group: ").strip()
            if not choice.isdigit():
                print("Invalid group.")
                continue
            group_id = int(choice)
            try:
                address, added, account_index = _add_account_from_mnemonic_group(group_id)
            except ValueError as exc:
                print(str(exc))
                continue
            if added:
                print(f"Added account: {address} (mnemonic {group_id}.{account_index})")
            else:
                print(f"Account already exists: {address}")
        elif line == "5":
            with accounts_lock:
                if not accounts:
                    print("No accounts.")
                    continue
                for idx, entry in enumerate(accounts):
                    default_marker = " (default)" if default_account_index == idx else ""
                    label = _format_account_label(entry, idx)
                    print(f"{label}: {entry['address']} [{entry['source']}] {default_marker}")
        elif line == "6":
            with accounts_lock:
                if not accounts:
                    print("No accounts to select.")
                    continue
                for idx, entry in enumerate(accounts):
                    default_marker = " (default)" if default_account_index == idx else ""
                    label = _format_account_label(entry, idx)
                    print(f"{label}: {entry['address']} {default_marker}")
            choice = input("Select index (e.g. 2.1): ").strip()
            account_idx = _find_account_index_from_selector(choice)
            if account_idx is None:
                print("Invalid index.")
                continue
            with accounts_lock:
                if account_idx < 0 or account_idx >= len(accounts):
                    print("Index out of range.")
                    continue
                default_account_index = account_idx
                print(f"Default account set to {accounts[default_account_index]['address']}")
        elif line == "7":
            with pending_lock:
                if not pending_sign_requests:
                    print("No pending sign requests.")
                    continue
                for entry in pending_sign_requests:
                    tx = entry["tx"] or {}
                    to_addr = tx.get("to", "")
                    from_addr = tx.get("from", "")
                    value = tx.get("value", "")
                    data = tx.get("data", "")
                    print(
                        f"{entry['pending_id']}: {entry['method']} from={from_addr} to={to_addr} "
                        f"value={value} data={data}"
                    )
        elif line:
            print("Unknown option.")

    if ioloop is not None:
        ioloop.add_callback(ioloop.stop)


if __name__ == "__main__":
    port = 5333
    server_thread, server_ioloop = start_server_in_thread(port)
    cli_loop(server_ioloop)
    server_thread.join(timeout=2)
