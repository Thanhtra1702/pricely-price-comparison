import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

UNIT_PATTERN = re.compile(r"(?P<multiplier>\d+)\s*(?:hop|chai|goi|loc|lon)?\s*[x×]\s*(?P<quantity>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|ml|l|lit)\b|(?P<single>\d+(?:[.,]\d+)?)\s*(?P<single_unit>kg|g|ml|l|lit)\b", re.I)


@dataclass(frozen=True)
class ProductSignature:
    normalized_name: str
    normalized_brand: str
    quantity: float | None
    unit: str | None
    multiplier: int


def normalize_text(value: str | None) -> str:
    value = (value or "").replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFD", value).encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_package(value: str | None) -> tuple[float | None, str | None, int]:
    match = UNIT_PATTERN.search(normalize_text(value))
    if not match:
        return None, None, 1
    multiplier = int(match.group("multiplier") or 1)
    quantity = float((match.group("quantity") or match.group("single")).replace(",", "."))
    unit = (match.group("unit") or match.group("single_unit")).lower()
    if unit == "lit":
        unit = "l"
    if unit == "kg":
        quantity, unit = quantity * 1000, "g"
    elif unit == "l":
        quantity, unit = quantity * 1000, "ml"
    return quantity, unit, multiplier


def signature(name: str | None, brand: str | None = None) -> ProductSignature:
    quantity, unit, multiplier = extract_package(name)
    normalized_brand = normalize_text(brand)
    normalized_brand = re.sub(r"\b(viet nam|vietnam)\b", "", normalized_brand).strip()
    return ProductSignature(normalize_text(name), normalized_brand, quantity, unit, multiplier)


def match_confidence(left: ProductSignature, right: ProductSignature) -> float:
    brands_compatible = not left.normalized_brand or not right.normalized_brand or left.normalized_brand in right.normalized_brand or right.normalized_brand in left.normalized_brand
    if not brands_compatible:
        return 0.0
    if left.quantity and right.quantity and (left.unit != right.unit or left.quantity != right.quantity or left.multiplier != right.multiplier):
        return 0.0
    name_score = SequenceMatcher(None, left.normalized_name, right.normalized_name).ratio()
    brand_score = 1.0 if left.normalized_brand and right.normalized_brand and brands_compatible else 0.0
    package_score = 1.0 if left.quantity and left.quantity == right.quantity and left.unit == right.unit and left.multiplier == right.multiplier else 0.0
    return round(name_score * 0.65 + brand_score * 0.20 + package_score * 0.15, 3)


def is_reliable_match(left: ProductSignature, right: ProductSignature) -> bool:
    return match_confidence(left, right) >= 0.78
