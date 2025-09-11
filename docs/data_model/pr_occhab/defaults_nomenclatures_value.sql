
\restrict n6EJHP68Jpue11N6s8r6n3kLLCXLn4b0fYArmsKx4cD3MX1TmrNWJmGbRems6Xj

CREATE TABLE pr_occhab.defaults_nomenclatures_value (
    mnemonique_type character varying(255) NOT NULL,
    id_organism integer DEFAULT 0 NOT NULL,
    id_nomenclature integer NOT NULL
);

ALTER TABLE ONLY pr_occhab.defaults_nomenclatures_value
    ADD CONSTRAINT pk_pr_occhab_defaults_nomenclatures_value PRIMARY KEY (mnemonique_type, id_organism);

ALTER TABLE ONLY pr_occhab.defaults_nomenclatures_value
    ADD CONSTRAINT fk_pr_occhab_defaults_nomenclatures_value_id_nomenclature FOREIGN KEY (id_nomenclature) REFERENCES ref_nomenclatures.t_nomenclatures(id_nomenclature) ON UPDATE CASCADE;

ALTER TABLE ONLY pr_occhab.defaults_nomenclatures_value
    ADD CONSTRAINT fk_pr_occhab_defaults_nomenclatures_value_id_organism FOREIGN KEY (id_organism) REFERENCES utilisateurs.bib_organismes(id_organisme) ON UPDATE CASCADE;

ALTER TABLE ONLY pr_occhab.defaults_nomenclatures_value
    ADD CONSTRAINT fk_pr_occhab_defaults_nomenclatures_value_mnemonique_type FOREIGN KEY (mnemonique_type) REFERENCES ref_nomenclatures.bib_nomenclatures_types(mnemonique) ON UPDATE CASCADE;

\unrestrict n6EJHP68Jpue11N6s8r6n3kLLCXLn4b0fYArmsKx4cD3MX1TmrNWJmGbRems6Xj

