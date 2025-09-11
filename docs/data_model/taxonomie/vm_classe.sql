
\restrict ed1JeeVdAUIhzi6BefaNWuD4snU3K8f5rTFOxSinEEAuyEJO6UoeMPeo6ylxm1R

CREATE MATERIALIZED VIEW taxonomie.vm_classe AS
 SELECT DISTINCT tx.classe
   FROM taxonomie.taxref tx
  WITH NO DATA;

CREATE UNIQUE INDEX i_unique_classe ON taxonomie.vm_classe USING btree (classe);

\unrestrict ed1JeeVdAUIhzi6BefaNWuD4snU3K8f5rTFOxSinEEAuyEJO6UoeMPeo6ylxm1R

