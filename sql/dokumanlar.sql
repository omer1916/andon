-- Kılavuz tabloları. scripts/ingest.py her çalıştığında bu dosyayla tabloları yeniden kurar.
-- Operasyon verisinden (sql/schema.sql) ayrıdır: seed çalıştırmak kılavuzları silmez.
--
-- Vektör indeksi (HNSW) bilerek yok. Birkaç yüz parçada tam tarama hem hızlı hem kesin
-- sonuç verir; ayrıca yetki filtresi (5. hafta) eklendiğinde indeksli aramanın filtreden
-- sonra k'dan az sonuç döndürme sorunu yaşanmaz. Parça sayısı on binlere çıkarsa
-- "USING hnsw (embedding vector_cosine_ops)" indeksi ve hnsw.iterative_scan açılmalı.

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS dokuman_parcalari, dokumanlar;

CREATE TABLE dokumanlar (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kod           text    NOT NULL UNIQUE,        -- örn. PRES-BK-01
    baslik        text    NOT NULL,
    dosya         text    NOT NULL,
    erisim        text    NOT NULL CHECK (erisim IN ('operasyon', 'bakim')),
    sayfa_sayisi  integer NOT NULL
);

CREATE TABLE dokuman_parcalari (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dokuman_id  integer     NOT NULL REFERENCES dokumanlar (id),
    sayfa       integer     NOT NULL,
    bolum       text,                           -- örn. "4. HİDROLİK ... > 4.1 Genel yaklaşım"
    icerik      text        NOT NULL,
    embedding   vector(384) NOT NULL            -- multilingual-e5-small
);
CREATE INDEX ON dokuman_parcalari (dokuman_id);
