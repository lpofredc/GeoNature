
\restrict HnST9Hst5VP6tTYYJ5qovNZ58gIaHWsi7Scce2OTnVs7edUHRFBt0VpqJJc2BIJ

CREATE TABLE taxonomie.bib_taxref_statuts (
    id_statut character(1) NOT NULL,
    nom_statut character varying(50) NOT NULL
);

ALTER TABLE ONLY taxonomie.bib_taxref_statuts
    ADD CONSTRAINT pk_bib_taxref_statuts PRIMARY KEY (id_statut);

\unrestrict HnST9Hst5VP6tTYYJ5qovNZ58gIaHWsi7Scce2OTnVs7edUHRFBt0VpqJJc2BIJ

