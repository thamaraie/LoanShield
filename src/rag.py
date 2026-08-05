"""ChromaDB-backed retrieval-augmented asset suggestions."""

from dataclasses import dataclass
import os
from typing import Any

from dotenv import load_dotenv
import httpx
import truststore

load_dotenv()
truststore.inject_into_ssl()


@dataclass(frozen=True)
class RetrievedAsset:
    """Asset context retrieved from ChromaDB."""

    name: str
    value: float
    source_page: int
    context: str


class GroqExplainer:
    """Use Groq only to rewrite grounded retrieval context into plain language."""

    def __init__(self) -> None:
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.base_url = os.getenv(
            "GROQ_API_BASE_URL", "https://api.groq.com/openai/v1"
        ).rstrip("/")
        self.enabled = os.getenv("GROQ_ENABLED", "false").lower() == "true"

    def explain(
        self,
        company_name: str,
        minimum_value: float,
        asset: RetrievedAsset | None,
    ) -> str | None:
        """Return a grounded explanation, or None so the caller can use its fallback."""
        if not self.enabled or not self.api_key or asset is None:
            return None
        prompt = (
            "Explain this compliance suggestion in one concise sentence. "
            "Use only the supplied facts. Do not change the asset, value, or source page. "
            f"Company: {company_name}. Minimum required value: EUR {minimum_value:,.0f}. "
            f"Selected asset: {asset.name}. Asset value: EUR {asset.value:,.0f}. "
            f"Source page: {asset.source_page}."
        )
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "max_tokens": 100,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You write audit-friendly compliance explanations.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=15,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return content.strip() or None
        except (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError):
            return None


class ChromaAssetStore:
    """Store and retrieve asset documents with ChromaDB embeddings."""

    def __init__(
        self,
        path: str = "data/chroma",
        model_name: str | None = None,
    ) -> None:
        self.path = path
        self.model_name = model_name or os.getenv(
            "EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"
        )
        if "/" not in self.model_name:
            self.model_name = f"BAAI/{self.model_name}"
        self._client = None
        self._collection = None

    def _get_collection(self):
        """Create the persistent Chroma collection only when first used."""
        if self._collection is None:
            import chromadb
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            self._client = chromadb.PersistentClient(path=self.path)
            embedding_function = SentenceTransformerEmbeddingFunction(
                model_name=self.model_name,
                normalize_embeddings=True,
            )
            self._collection = self._client.get_or_create_collection(
                name="loan_guard_assets",
                embedding_function=embedding_function,
            )
        return self._collection

    def close(self) -> None:
        """Release ChromaDB file handles, especially on Windows."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._collection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def index_profiles(self, profiles: dict[str, dict[str, Any]]) -> None:
        """Index one grounded document for every profile asset."""
        collection = self._get_collection()
        documents = []
        ids = []
        metadatas = []
        for profile in profiles.values():
            for asset_index, asset in enumerate(profile["assets"]):
                asset_id = f"{profile['name']}::{asset['name']}::{asset_index}"
                documents.append(
                    f"Company {profile['name']}; asset {asset['name']}; "
                    f"value {asset['value']:,.0f}; source page {profile['source_page']}."
                )
                ids.append(asset_id)
                metadatas.append(
                    {
                        "company_name": profile["name"],
                        "asset_name": asset["name"],
                        "asset_value": float(asset["value"]),
                        "source_page": int(profile["source_page"]),
                    }
                )
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def retrieve(
        self,
        profile: dict[str, Any],
        minimum_value: float,
    ) -> list[RetrievedAsset]:
        """Retrieve company asset context relevant to the coverage query."""
        collection = self._get_collection()
        result = collection.query(
            query_texts=[
                f"{profile['name']} asset covering at least {minimum_value:,.0f}"
            ],
            where={"company_name": profile["name"]},
            n_results=max(len(profile["assets"]), 1),
        )
        metadata = result["metadatas"][0] if result["metadatas"] else []
        return [
            RetrievedAsset(
                name=item["asset_name"],
                value=item["asset_value"],
                source_page=item["source_page"],
                context=(
                    f"Company: {profile['name']}; asset: {item['asset_name']}; "
                    f"value: {item['asset_value']:,.0f}; source page {item['source_page']}."
                ),
            )
            for item in metadata
            if item["asset_value"] >= minimum_value
        ]


class AssetRag:
    """Retrieve grounded context and generate a deterministic explanation."""

    def __init__(
        self,
        store: ChromaAssetStore | None = None,
        explainer: GroqExplainer | None = None,
    ) -> None:
        self.store = store
        self.explainer = explainer or GroqExplainer()

    def retrieve(self, profile: dict[str, Any], minimum_value: float) -> list[RetrievedAsset]:
        """Retrieve and deterministically filter qualifying asset context."""
        if self.store is None:
            assets = [
                RetrievedAsset(
                    name=asset["name"],
                    value=asset["value"],
                    source_page=profile["source_page"],
                    context=(
                        f"Company: {profile['name']}; asset: {asset['name']}; "
                        f"value: {asset['value']:,.0f}; source page {profile['source_page']}."
                    ),
                )
                for asset in profile["assets"]
                if asset["value"] >= minimum_value
            ]
        else:
            assets = self.store.retrieve(profile, minimum_value)
        return sorted(assets, key=lambda asset: (asset.value, asset.name))

    def generate(self, company_name: str, minimum_value: float, assets: list[RetrievedAsset]) -> str:
        """Generate a grounded explanation with a deterministic fallback."""
        if not assets:
            return f"No asset in the {company_name} profile covers EUR {minimum_value:,.0f}."
        asset = assets[0]
        llm_explanation = self.explainer.explain(company_name, minimum_value, asset)
        if llm_explanation:
            return llm_explanation
        return (
            f"Use {asset.name}, the smallest retrieved profile asset covering "
            f"50% of the loan (EUR {minimum_value:,.0f}); source page {asset.source_page}."
        )

    def suggest(self, profile: dict[str, Any], minimum_value: float) -> tuple[RetrievedAsset | None, str]:
        """Retrieve grounded asset context and generate its explanation."""
        assets = self.retrieve(profile, minimum_value)
        asset = assets[0] if assets else None
        return asset, self.generate(profile["name"], minimum_value, assets)
