
\restrict Ancw2ZGljCjaO7KIOswQ0sqdT6Q816sOJaFTLgrAtqaEg0pULTcmTnrGVRh2Lpb

CREATE TABLE taxonomie.bib_taxref_rangs (
    id_rang character(4) NOT NULL,
    nom_rang character varying(50) NOT NULL,
    nom_rang_en character varying(50) NOT NULL,
    tri_rang integer
);

ALTER TABLE ONLY taxonomie.bib_taxref_rangs
    ADD CONSTRAINT pk_bib_taxref_rangs PRIMARY KEY (id_rang);

\unrestrict Ancw2ZGljCjaO7KIOswQ0sqdT6Q816sOJaFTLgrAtqaEg0pULTcmTnrGVRh2Lpb

