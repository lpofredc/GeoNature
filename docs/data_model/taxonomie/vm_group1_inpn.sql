
\restrict l2tlFMt1KjXAKVlLPCDV6OdekvBzb3rRlAODSWB1yc7Kq7FVFzCOvD5MYuQbs1v

CREATE MATERIALIZED VIEW taxonomie.vm_group1_inpn AS
 SELECT DISTINCT tx.group1_inpn
   FROM taxonomie.taxref tx
  WITH NO DATA;

CREATE UNIQUE INDEX i_unique_group1_inpn ON taxonomie.vm_group1_inpn USING btree (group1_inpn);

\unrestrict l2tlFMt1KjXAKVlLPCDV6OdekvBzb3rRlAODSWB1yc7Kq7FVFzCOvD5MYuQbs1v

