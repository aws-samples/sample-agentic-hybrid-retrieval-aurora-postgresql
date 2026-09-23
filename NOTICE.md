# Notice

The source code in this repository is licensed under the MIT No Attribution
License (see [LICENSE](LICENSE)). The datasets below are third-party works under
their own terms; the code license does not apply to them.

## Served catalog: Amazon Reviews 2023

The workshop catalog `reviews-2023-500k-v1` holds 500,000 product records
selected from the Electronics and Office Products metadata of **Amazon Reviews
2023**, published by the McAuley Lab at UC San Diego
(<https://amazon-reviews-2023.github.io/>, Hugging Face dataset
`McAuley-Lab/Amazon-Reviews-2023`). 2,327 review excerpts for 476 products come
from the same dataset's review files. Product photos are loaded from the image URLs in
those records and are not copied into this repository.

> Yupeng Hou, Jiacheng Li, Zhankui He, An Yan, Xiusi Chen, and Julian McAuley.
> 2024. *Bridging Language and Items for Retrieval and Recommendation.*
> arXiv:2403.03952.

The publisher does not state a license for this dataset. Public redistribution of
the prepared catalog bundle is unresolved and is an event-owner release
requirement; see [docs/catalog-source-assessment.md](docs/catalog-source-assessment.md).
Product names, brands and trademarks belong to their owners. Ratings are
historical dataset values; the catalog carries no current prices or availability.

## Teaching comparisons: Amazon ESCI and Wayfair WANDS

Five reviewed comparisons in `data/evals/references/` use labels from these
datasets. They are not part of the searched catalog, ranking or embeddings.

- **Shopping Queries Dataset (ESCI)**, Apache License 2.0. License and notice are
  retained in `data/evals/references/licenses/`.
  > Chandan K. Reddy, Lluís Màrquez, Fran Valero, Nikhil Rao, Hugo Zaragoza,
  > Sambaran Bandyopadhyay, Arnab Biswas, Anlu Xing, and Karthik Subbian. 2022.
  > *Shopping Queries Dataset: A Large-Scale ESCI Benchmark for Improving Product
  > Search.* arXiv:2206.06588.
- **WANDS: Wayfair ANnotation DataSet**, MIT License, retained in
  `data/evals/references/licenses/`.
  > Yan Chen, Shujian Liu, Zheng Liu, Weiyi Sun, Linas Baltrunas, and Benjamin
  > Schroeder. 2022. *WANDS: Dataset for Product Search Relevance Assessment.* In
  > Proceedings of the 44th European Conference on Information Retrieval (ECIR).

## Generated data

Embeddings are generated in this project with Amazon Bedrock (Cohere Embed v4).
The historical synthetic catalog in the base bootstrap, which is retained only
for shared tables and historical benchmarks, contains invented products, brands,
reviews and performance values. It does not describe a real retailer.
