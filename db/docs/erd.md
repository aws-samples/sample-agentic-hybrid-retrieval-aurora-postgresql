# Entity relationship diagram

```mermaid
erDiagram
    BRAND ||--o{ PRODUCT : owns
    CATEGORY ||--o{ PRODUCT : classifies
    CATEGORY ||--o{ CATEGORY : parent_of
    PRODUCT ||--|| PRODUCT_OFFER : has_current
    PRODUCT ||--o| MERCHANDISING_ASSIGNMENT : merchandised_as
    PRODUCT ||--o{ PRODUCT_MEDIA : uses
    MEDIA_ASSET ||--o{ PRODUCT_MEDIA : assigned_to
    PRODUCT ||--o{ PRODUCT_EVIDENCE : supported_by
    PRODUCT ||--|| PRODUCT_DOCUMENT : projected_as
    PRODUCT ||--o{ JUDGMENT : judged_in
    EVAL_QUERY ||--o{ JUDGMENT : has
    SEARCH_EVENT ||--o{ SEARCH_RESULT_EVENT : returns
    AGENT_TURN ||--o{ AGENT_TOOL_EVENT : invokes

    BRAND {
        bigint brand_id PK
        text brand_key UK
        text display_name
    }
    CATEGORY {
        bigint category_id PK
        product_domain domain
        bigint parent_category_id FK
        text category_path
    }
    PRODUCT {
        bigint product_id PK
        uuid product_uid UK
        text sku UK
        bigint brand_id FK
        bigint category_id FK
        text canonical_group_id
        jsonb attributes
    }
    PRODUCT_OFFER {
        bigint product_id PK_FK
        bigint price_cents
        availability_status availability
        numeric rating
        real quality_score
    }
    PRODUCT_DOCUMENT {
        bigint product_id PK_FK
        tsvector search_document
        text trigram_text
        text embedding_text
        text rerank_text
        vector embedding
    }
    PRODUCT_EVIDENCE {
        bigint evidence_id PK
        bigint product_id FK
        evidence_type evidence_type
        text evidence_text
        vector embedding
    }
    MERCHANDISING_ASSIGNMENT {
        bigint product_id PK_FK
        media_tier media_tier
        smallint shop_page
        smallint shop_position
        boolean is_flagship
        boolean is_retrieval_anchor
    }
    MEDIA_ASSET {
        uuid asset_id PK
        text asset_key UK
        text runtime_uri
        text aspect_ratio
    }
    PRODUCT_MEDIA {
        bigint product_id FK
        uuid asset_id FK
        media_role role
        jsonb mark_zone
    }
```
