# b0x stand for a lockbox for 0x address
# there is a master key and a authenticator
# the master key is loaded sk from encrypted file
# the authenticator approve a sign
# it is used to approve for the signature during the agent chat

import argparse
import json
import getpass
import os
import pyotp
import qrcode
from eth_account import Account
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
        return account
    except Exception as e:
        print(f"Error: Failed to decrypt key. Incorrect password? ({e})")
        return None

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

def run_b0x(args):
    print(f"Starting lockb0x on port {args.port}...")
    # TODO: Implement authenticator service
    pass

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
    run_parser.set_defaults(func=run_b0x)


    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
