"""Knowledge base: compliance rulebook chunks stored as vectors in Azure AI Search."""

from langchain_community.vectorstores.azuresearch import AzureSearch
from langchain_openai import AzureOpenAIEmbeddings

from brand_guardian.config import Settings


def get_embeddings(settings: Settings) -> AzureOpenAIEmbeddings:
    return AzureOpenAIEmbeddings(
        azure_endpoint=settings.openai_endpoint,
        api_key=settings.openai_api_key,
        api_version=settings.openai_api_version,
        azure_deployment=settings.embedding_deployment,
    )


def get_vector_store(settings: Settings) -> AzureSearch:
    return AzureSearch(
        azure_search_endpoint=settings.search_endpoint,
        azure_search_key=settings.search_api_key,
        index_name=settings.search_index_name,
        embedding_function=get_embeddings(settings).embed_query,
    )
