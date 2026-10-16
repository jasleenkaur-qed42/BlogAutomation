---
title: RAG Pipelines Explained
slug: rag-pipelines-explained
---
# RAG Pipelines Explained

Retrieval-augmented generation lets a model answer from your documents instead of from memory alone.

## How the pipeline fits together
Documents are split into chunks, embedded and stored. A question is embedded, the closest chunks are retrieved, and the model answers from them.

## Choosing a chunking strategy
Fixed-size chunks are simple. Sentence-aware chunks keep meaning intact. Structure-aware chunks follow headings and tables.

## A retrieval sketch
The retrieval step ranks chunks by similarity to the question.

```python
def retrieve(question, index, k=4):
    return index.search(embed(question), k)
```

## Conclusion
Good retrieval matters more than a bigger model.
