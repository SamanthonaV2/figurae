from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ETH_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
DECIMAL_AMOUNT = re.compile(r"^(?:0|[1-9][0-9]{0,39})(?:\.[0-9]{1,18})?$")


def decimal_string(value: str) -> str:
    if not DECIMAL_AMOUNT.fullmatch(value) or Decimal(value) <= 0:
        raise ValueError("Numero positivo in formato decimale, massimo 18 cifre decimali (senza esponenti)")
    return value


def wallet_address(value: str, allow_empty: bool = False) -> str:
    if allow_empty and not value:
        return value
    if not ETH_ADDRESS.fullmatch(value):
        raise ValueError("Indirizzo Ethereum richiesto: 0x seguito da 40 caratteri esadecimali")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Password(StrictModel):
    password: str = Field(min_length=1, max_length=256)


class Founder(StrictModel):
    address: str = Field(default="", max_length=42)
    bps: int = Field(gt=0, le=3000)

    @field_validator("address")
    @classmethod
    def validate_address(cls, value):
        return wallet_address(value, allow_empty=True)


class Settings(StrictModel):
    network_name: str = Field(default="Sepolia", min_length=1, max_length=120)
    chain_id: int = Field(default=11155111, gt=0, le=2**53 - 1)
    contract_address: str = Field(default="", max_length=42)
    distribution_wallet: str = Field(default="", max_length=42)
    founders: list[Founder] = Field(default_factory=lambda: [Founder(address="", bps=3000)], min_length=1, max_length=50)
    project_description: str = Field(default="Meme token Figurae ispirato all'intelligenza artificiale.", max_length=5000)
    website: str = Field(default="", max_length=300)
    contact: str = Field(default="", max_length=300)

    @field_validator("contract_address", "distribution_wallet")
    @classmethod
    def validate_address(cls, value):
        return wallet_address(value, allow_empty=True)

    @model_validator(mode="after")
    def allocations(self):
        if sum(founder.bps for founder in self.founders) != 3000:
            raise ValueError("La quota aggregata dei fondatori deve essere 3000 bps (30%)")
        filled = [f.address.lower() for f in self.founders if f.address]
        if len(filled) != len(set(filled)):
            raise ValueError("Indirizzi dei fondatori duplicati")
        if self.distribution_wallet and self.distribution_wallet.lower() in filled:
            raise ValueError("Il wallet di distribuzione deve essere distinto dai fondatori")
        if any(address.lower() == "0x" + "0" * 40 for address in filled + [self.distribution_wallet, self.contract_address] if address):
            raise ValueError("L'indirizzo zero non è consentito")
        return self


class SaleCreate(StrictModel):
    customer: str = Field(min_length=1, max_length=200)
    wallet_address: str = Field(max_length=42)
    quantity: str = Field(max_length=60)
    unit_price_eur: str = Field(max_length=60)
    payment_currency: Literal["EUR", "ETH", "QNT"] = "EUR"
    notes: str = Field(default="", max_length=3000)

    @field_validator("wallet_address")
    @classmethod
    def validate_wallet(cls, value):
        value = wallet_address(value)
        if value.lower() == "0x" + "0" * 40:
            raise ValueError("Il wallet non può essere l'indirizzo zero")
        return value

    @field_validator("quantity", "unit_price_eur")
    @classmethod
    def validate_amount(cls, value):
        return decimal_string(value)


class SaleUpdate(StrictModel):
    status: Literal["paid", "completed", "cancelled"]
    payment_reference: str | None = Field(default=None, max_length=300)
    tx_hash: str | None = Field(default=None, max_length=66)

    @field_validator("tx_hash")
    @classmethod
    def validate_hash(cls, value):
        if value and not TX_HASH.fullmatch(value):
            raise ValueError("Hash transazione richiesto: 0x seguito da 64 caratteri esadecimali")
        return value


class DeliveryCreate(StrictModel):
    tx_hash: str = Field(min_length=66, max_length=66)
    chain_id: int = Field(gt=0, le=2**53 - 1)
    contract_address: str = Field(min_length=42, max_length=42)

    @field_validator("tx_hash")
    @classmethod
    def validate_hash(cls, value):
        if not TX_HASH.fullmatch(value):
            raise ValueError("Hash transazione richiesto: 0x seguito da 64 caratteri esadecimali")
        return value

    @field_validator("contract_address")
    @classmethod
    def validate_contract(cls, value):
        value = wallet_address(value)
        if value.lower() == "0x" + "0" * 40:
            raise ValueError("L'indirizzo del contratto non può essere zero")
        return value


class PriceCreate(StrictModel):
    price_eur: str = Field(max_length=60)
    source: str = Field(min_length=1, max_length=200)

    @field_validator("price_eur")
    @classmethod
    def validate_amount(cls, value):
        return decimal_string(value)


class WhitepaperFields(StrictModel):
    mission: str = Field(default="Costruire una community creativa attorno a un meme token ispirato all'IA.", max_length=12000)
    utility: str = Field(default="Nessuna utility operativa garantita: branding IA e community.", max_length=12000)
    roadmap: str = Field(default="Prototipo locale; verifica del contratto; eventuale testnet; piano di distribuzione da definire.", max_length=12000)
    sale_policy: str = Field(default="Vendite registrate manualmente; pagamento e consegna devono essere verificati dal gestore.", max_length=12000)
    notes: str = Field(default="", max_length=12000)


class WhitepaperUpdate(StrictModel):
    fields: WhitepaperFields


class ChainTransaction(StrictModel):
    sender: Literal["alice", "bob", "carol"]
    kind: Literal["transfer", "stake", "unstake", "ai_result"]
    amount: int | None = Field(default=None, gt=0, le=2**63 - 1)
    recipient: str | None = Field(default=None, max_length=64)
    text: str | None = Field(default=None, max_length=16000)


class ForgeRequest(StrictModel):
    sender: Literal["alice", "bob", "carol"] | None = None
