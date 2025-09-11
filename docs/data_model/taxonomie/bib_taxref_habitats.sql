
\restrict F83fpWrTGhpPwEklMYGAGjbDLhMhmGxtZso6TEd4qh8jqIukA3haM5zyMbrdIZJ

CREATE TABLE taxonomie.bib_taxref_habitats (
    id_habitat integer NOT NULL,
    nom_habitat character varying(50) NOT NULL,
    desc_habitat text
);

ALTER TABLE ONLY taxonomie.bib_taxref_habitats
    ADD CONSTRAINT pk_bib_taxref_habitats PRIMARY KEY (id_habitat);

\unrestrict F83fpWrTGhpPwEklMYGAGjbDLhMhmGxtZso6TEd4qh8jqIukA3haM5zyMbrdIZJ

