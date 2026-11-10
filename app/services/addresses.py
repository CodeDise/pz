"""Wallet address validation (format + checksum where the chain has one)."""
import hashlib
import re

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def valid_tron(address: str) -> bool:
    try:
        n = 0
        for ch in address:
            n = n * 58 + _B58.index(ch)
        raw = n.to_bytes(25, "big")
    except (ValueError, OverflowError):
        return False
    payload, checksum = raw[:21], raw[21:]
    if payload[0] != 0x41:
        return False
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == checksum


def valid_evm(address: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", address))


def valid_address(network: str, address: str) -> bool:
    if network == "TRC20":
        return valid_tron(address)
    if network == "BEP20":
        return valid_evm(address)
    return False
