from app.products.base import ProductAdapter, infer_product_type
from app.products.metadata import NormalizedProductMetadata, ValidationReport
from app.products.registry import adapter_catalog, get_adapter

__all__ = [
    "ProductAdapter",
    "NormalizedProductMetadata",
    "ValidationReport",
    "get_adapter",
    "adapter_catalog",
    "infer_product_type",
]
