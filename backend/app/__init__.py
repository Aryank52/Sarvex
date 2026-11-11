"""SARVEX backend package.

The product is organized as a layered scientific system:

connectors -> products/adapters -> storage manifests -> processing -> events
-> evidence/RAG -> copilot explanations -> reports.

The LLM layer never becomes the source of truth: measurements and provenance
are persisted before any explanation is generated.
"""

__version__ = "1.0.0"
