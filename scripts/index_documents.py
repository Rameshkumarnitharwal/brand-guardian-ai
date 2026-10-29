"""Build the knowledge base: chunk compliance rulebook PDFs and push vectors to Azure AI Search.

Usage: python scripts/index_documents.py [--data-dir data/rulebooks]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_community.document_loaders import PyPDFLoader  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from brand_guardian.config import get_settings  # noqa: E402
from brand_guardian.services.knowledge_base import get_vector_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/rulebooks"))
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    args = parser.parse_args()

    pdfs = sorted(args.data_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {args.data_dir}. Add rulebooks (e.g. FTC Endorsement Guides) and re-run.")
        return 1

    splitter = RecursiveCharacterTextSplitter(chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    chunks = []
    for pdf in pdfs:
        pages = PyPDFLoader(str(pdf)).load()
        for page in pages:
            page.metadata["source"] = pdf.name
        doc_chunks = splitter.split_documents(pages)
        print(f"{pdf.name}: {len(pages)} pages -> {len(doc_chunks)} chunks")
        chunks.extend(doc_chunks)

    store = get_vector_store(get_settings())
    store.add_documents(chunks)
    print(f"Indexed {len(chunks)} chunks into '{get_settings().search_index_name}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
