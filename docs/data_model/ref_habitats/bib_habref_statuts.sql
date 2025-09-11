
\restrict QYfF4vHBCyY3fGVo9tGQhV6QZQ1UdqB9hEE5WJckRnKT4q0VLdqxmWw4TycBDZJ

CREATE TABLE ref_habitats.bib_habref_statuts (
    statut character varying(1) NOT NULL,
    description character varying(50) NOT NULL,
    definition character varying(500) NOT NULL,
    ordre integer
);

COMMENT ON TABLE ref_habitats.bib_habref_statuts IS 'Bibliothèque des types statut d''habitat - Présence, absence ... - Table habref_status de HABREF';

ALTER TABLE ONLY ref_habitats.bib_habref_statuts
    ADD CONSTRAINT pk_bib_habref_statuts PRIMARY KEY (statut);

\unrestrict QYfF4vHBCyY3fGVo9tGQhV6QZQ1UdqB9hEE5WJckRnKT4q0VLdqxmWw4TycBDZJ

