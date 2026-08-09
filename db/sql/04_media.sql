\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS mosaic.media_asset (
    asset_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_key            text NOT NULL UNIQUE,
    tier                 mosaic.media_tier NOT NULL,
    master_uri           text,
    runtime_uri          text NOT NULL,
    mime_type            text NOT NULL DEFAULT 'image/webp',
    width_px             integer NOT NULL CHECK (width_px > 0),
    height_px            integer NOT NULL CHECK (height_px > 0),
    aspect_ratio         text NOT NULL,
    sha256_hex           text,
    is_bespoke           boolean NOT NULL DEFAULT false,
    generation_metadata  jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mosaic.product_media (
    product_id        bigint NOT NULL REFERENCES mosaic.product(product_id) ON DELETE CASCADE,
    asset_id          uuid NOT NULL REFERENCES mosaic.media_asset(asset_id) ON DELETE RESTRICT,
    role              mosaic.media_role NOT NULL,
    sort_order        smallint NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    crop_anchor_x     numeric(5,4) NOT NULL DEFAULT 0.5 CHECK (crop_anchor_x BETWEEN 0 AND 1),
    crop_anchor_y     numeric(5,4) NOT NULL DEFAULT 0.5 CHECK (crop_anchor_y BETWEEN 0 AND 1),
    mark_zone         jsonb NOT NULL DEFAULT '{}'::jsonb,
    alt_text          text,
    metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, role, sort_order),
    UNIQUE (product_id, asset_id, role)
);

COMMENT ON COLUMN mosaic.product_media.mark_zone IS
'Normalized physical area reserved for post-composited Mosaic mark, for example {"x":0.72,"y":0.32,"w":0.16,"h":0.12,"surface":"outer_earcup"}.';

CREATE INDEX IF NOT EXISTS product_media_asset_idx
    ON mosaic.product_media (asset_id);
CREATE INDEX IF NOT EXISTS product_media_catalog_idx
    ON mosaic.product_media (product_id, sort_order)
    WHERE role = 'catalog';
CREATE INDEX IF NOT EXISTS product_media_detail_idx
    ON mosaic.product_media (product_id, sort_order)
    WHERE role = 'detail';

DROP TRIGGER IF EXISTS media_asset_set_updated_at ON mosaic.media_asset;
CREATE TRIGGER media_asset_set_updated_at
BEFORE UPDATE ON mosaic.media_asset
FOR EACH ROW EXECUTE FUNCTION mosaic.set_updated_at();
