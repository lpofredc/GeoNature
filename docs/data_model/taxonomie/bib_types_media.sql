
\restrict Qle6ph5SnQ9G43bMAw1DwkeRGkRzgfHBey6IXd1MfVUbcKeAZ8kQuduAm7du3Sd

CREATE TABLE taxonomie.bib_types_media (
    id_type integer NOT NULL,
    nom_type_media character varying(100) NOT NULL,
    desc_type_media text
);

ALTER TABLE ONLY taxonomie.bib_types_media
    ADD CONSTRAINT id PRIMARY KEY (id_type);

\unrestrict Qle6ph5SnQ9G43bMAw1DwkeRGkRzgfHBey6IXd1MfVUbcKeAZ8kQuduAm7du3Sd

