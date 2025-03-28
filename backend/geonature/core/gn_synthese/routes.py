import json
import datetime
import re
from collections import OrderedDict
from warnings import warn

from flask import (
    Blueprint,
    abort,
    request,
    Response,
    current_app,
    send_from_directory,
    render_template,
    jsonify,
    g,
)
from geonature.core.gn_synthese.schemas import ReportSchema, SyntheseSchema
from geonature.core.gn_synthese.synthese_config import MANDATORY_COLUMNS
from pypnusershub.db.models import User
from pypnnomenclature.models import BibNomenclaturesTypes, TNomenclatures
from werkzeug.exceptions import Forbidden, NotFound, BadRequest, Conflict
from werkzeug.datastructures import MultiDict
from sqlalchemy import distinct, func, desc, asc, select, case, or_
from sqlalchemy.orm import joinedload, lazyload, selectinload, contains_eager, raiseload
from geojson import FeatureCollection, Feature
import sqlalchemy as sa
from sqlalchemy.orm import load_only, aliased, Load, with_expression
from sqlalchemy.exc import NoResultFound

from utils_flask_sqla.generic import serializeQuery, GenericTable
from utils_flask_sqla.response import to_csv_resp, to_json_resp, json_resp
from utils_flask_sqla_geo.generic import GenericTableGeo

from geonature.utils import filemanager
from geonature.utils.env import db, DB
from geonature.utils.errors import GeonatureApiError
from geonature.utils.utilsgeometrytools import export_as_geo_file

from geonature.core.gn_meta.models import TDatasets
from geonature.core.notifications.utils import dispatch_notifications

import geonature.core.gn_synthese.module
from geonature.core.gn_synthese.models import (
    BibReportsTypes,
    CorAreaSynthese,
    DefaultsNomenclaturesValue,
    Synthese,
    TSources,
    VSyntheseForWebApp,
    VColorAreaTaxon,
    TReport,
    SyntheseLogEntry,
)
from geonature.core.gn_synthese.synthese_config import MANDATORY_COLUMNS

from geonature.core.gn_synthese.utils.blurring import (
    build_allowed_geom_cte,
    build_blurred_precise_geom_queries,
    build_synthese_obs_query,
    split_blurring_precise_permissions,
)
from geonature.core.gn_synthese.utils.query_select_sqla import SyntheseQuery
from geonature.core.gn_synthese.utils.orm import is_already_joined

from geonature.core.gn_permissions import decorators as permissions
from geonature.core.gn_permissions.decorators import login_required, permissions_required
from geonature.core.gn_permissions.tools import get_scopes_by_action, get_permissions
from geonature.core.sensitivity.models import cor_sensitivity_area_type

from ref_geo.models import LAreas, BibAreasTypes

from apptax.taxonomie.models import (
    Taxref,
    bdc_statut_cor_text_area,
    Taxref,
    TaxrefBdcStatutCorTextValues,
    TaxrefBdcStatutTaxon,
    TaxrefBdcStatutText,
    TaxrefBdcStatutType,
    TaxrefBdcStatutValues,
    VMTaxrefListForautocomplete,
)

from geonature import app

routes = Blueprint("gn_synthese", __name__)


############################################
########### GET OBSERVATIONS  ##############
############################################


@routes.route("/for_web", methods=["GET", "POST"])
@permissions_required("R", module_code="SYNTHESE")
def get_observations_for_web(permissions):
    """Optimized route to serve data for the frontend with all filters.

    .. :quickref: Synthese; Get filtered observations

    Query filtered by any filter, returning all the fields of the
    view v_synthese_for_export::

        properties = {
            "id": r["id_synthese"],
            "date_min": str(r["date_min"]),
            "cd_nom": r["cd_nom"],
            "nom_vern_or_lb_nom": r["nom_vern"] if r["nom_vern"] else r["lb_nom"],
            "lb_nom": r["lb_nom"],
            "dataset_name": r["dataset_name"],
            "observers": r["observers"],
            "url_source": r["url_source"],
            "unique_id_sinp": r["unique_id_sinp"],
            "entity_source_pk_value": r["entity_source_pk_value"],
        }
        geojson = json.loads(r["st_asgeojson"])
        geojson["properties"] = properties

    :qparam str limit: Limit number of synthese returned. Defaults to NB_MAX_OBS_MAP.
    :qparam str cd_ref_parent: filtre tous les taxons enfants d'un TAXREF cd_ref.
    :qparam str cd_ref: Filter by TAXREF cd_ref attribute
    :qparam str taxonomy_group2_inpn: Filter by TAXREF group2_inpn attribute
    :qparam str taxonomy_id_hab: Filter by TAXREF id_habitat attribute
    :qparam str taxhub_attribut*: filtre générique TAXREF en fonction de l'attribut et de la valeur.
    :qparam str *_red_lists: filtre générique de listes rouges. Filtre sur les valeurs. Voir config.
    :qparam str *_protection_status: filtre générique de statuts (BdC Statuts). Filtre sur les types. Voir config.
    :qparam str observers: Filter on observer
    :qparam str id_organism: Filter on organism
    :qparam str date_min: Start date
    :qparam str date_max: End date
    :qparam str id_acquisition_framework: *tbd*
    :qparam str geoIntersection: Intersect with the geom send from the map
    :qparam str period_start: *tbd*
    :qparam str period_end: *tbd*
    :qparam str area*: Generic filter on area
    :qparam str *: Generic filter, given by colname & value
    :>jsonarr array data: Array of synthese with geojson key, see above
    :>jsonarr int nb_total: Number of observations
    :>jsonarr bool nb_obs_limited: Is number of observations capped
    """
    filters = request.json if request.is_json else {}
    if type(filters) != dict:
        raise BadRequest("Bad filters")
    result_limit = request.args.get(
        "limit", current_app.config["SYNTHESE"]["NB_MAX_OBS_MAP"], type=int
    )
    output_format = request.args.get("format", "ungrouped_geom")
    if output_format not in ["ungrouped_geom", "grouped_geom", "grouped_geom_by_areas"]:
        raise BadRequest(f"Bad format '{output_format}'")

    # Get Column Frontend parameter to return only the needed columns
    param_column_list = {
        col["prop"]
        for col in current_app.config["SYNTHESE"]["LIST_COLUMNS_FRONTEND"]
        + current_app.config["SYNTHESE"]["ADDITIONAL_COLUMNS_FRONTEND"]
    }
    # Init with compulsory columns
    columns = []
    for col in MANDATORY_COLUMNS:
        columns.extend([col, getattr(VSyntheseForWebApp, col)])

    if "count_min_max" in param_column_list:
        count_min_max = case(
            (
                VSyntheseForWebApp.count_min != VSyntheseForWebApp.count_max,
                func.concat(VSyntheseForWebApp.count_min, " - ", VSyntheseForWebApp.count_max),
            ),
            (
                VSyntheseForWebApp.count_min != None,
                func.concat(VSyntheseForWebApp.count_min),
            ),
            else_="",
        )
        columns += ["count_min_max", count_min_max]
        param_column_list.remove("count_min_max")

    if "nom_vern_or_lb_nom" in param_column_list:
        nom_vern_or_lb_nom = func.coalesce(
            func.nullif(VSyntheseForWebApp.nom_vern, ""), VSyntheseForWebApp.lb_nom
        )
        columns += ["nom_vern_or_lb_nom", nom_vern_or_lb_nom]
        param_column_list.remove("nom_vern_or_lb_nom")

    for column in param_column_list:
        columns += [column, getattr(VSyntheseForWebApp, column)]

    observations = func.json_build_object(*columns).label("obs_as_json")

    # Need to check if there are blurring permissions so that the blurring process
    # does not affect the performance if there is no blurring permissions
    blurring_permissions, precise_permissions = split_blurring_precise_permissions(permissions)
    if not blurring_permissions:
        # No need to apply blurring => same path as before blurring feature
        obs_query = (
            select(observations)
            .where(VSyntheseForWebApp.the_geom_4326.isnot(None))
            .order_by(VSyntheseForWebApp.date_min.desc())
            .limit(result_limit)
        )

        # Add filters to observations CTE query
        synthese_query_class = SyntheseQuery(
            VSyntheseForWebApp,
            obs_query,
            dict(filters),
        )
        synthese_query_class.apply_all_filters(g.current_user, permissions)
        obs_query = synthese_query_class.build_query()
        geojson_column = VSyntheseForWebApp.st_asgeojson
    else:
        # Build 2 queries that will be UNIONed
        # Select size hierarchy if mesh mode is selected
        select_size_hierarchy = output_format == "grouped_geom_by_areas"
        blurred_geom_query, precise_geom_query = build_blurred_precise_geom_queries(
            filters, select_size_hierarchy=select_size_hierarchy
        )

        allowed_geom_cte = build_allowed_geom_cte(
            blurring_permissions=blurring_permissions,
            precise_permissions=precise_permissions,
            blurred_geom_query=blurred_geom_query,
            precise_geom_query=precise_geom_query,
            limit=result_limit,
        )

        obs_query = build_synthese_obs_query(
            observations=observations,
            allowed_geom_cte=allowed_geom_cte,
            limit=result_limit,
        )
        geojson_column = func.st_asgeojson(allowed_geom_cte.c.geom)

    if output_format == "grouped_geom_by_areas":
        obs_query = obs_query.add_columns(VSyntheseForWebApp.id_synthese)
        # Need to select the size_hierarchy to use is after (only if blurring permissions are found)
        if blurring_permissions:
            obs_query = obs_query.add_columns(
                allowed_geom_cte.c.size_hierarchy.label("size_hierarchy")
            )
        obs_query = obs_query.cte("OBS")

        agg_areas = (
            select(CorAreaSynthese.id_synthese, LAreas.id_area)
            .join(CorAreaSynthese, CorAreaSynthese.id_area == LAreas.id_area)
            .join(BibAreasTypes, BibAreasTypes.id_type == LAreas.id_type)
            .where(CorAreaSynthese.id_synthese == obs_query.c.id_synthese)
            .where(
                BibAreasTypes.type_code == current_app.config["SYNTHESE"]["AREA_AGGREGATION_TYPE"]
            )
        )

        if blurring_permissions:
            # Do not select cells which size_hierarchy is bigger than AREA_AGGREGATION_TYPE
            # It means that we do not aggregate obs that have a blurring geometry greater in
            # size than the aggregation area
            agg_areas = agg_areas.where(obs_query.c.size_hierarchy <= BibAreasTypes.size_hierarchy)
        agg_areas = agg_areas.lateral("agg_areas")
        obs_query = (
            select(func.ST_AsGeoJSON(LAreas.geom_4326).label("geojson"), obs_query.c.obs_as_json)
            .select_from(
                obs_query.outerjoin(
                    agg_areas, agg_areas.c.id_synthese == obs_query.c.id_synthese
                ).outerjoin(LAreas, LAreas.id_area == agg_areas.c.id_area)
            )
            .cte("OBSERVATIONS")
        )
    else:
        obs_query = obs_query.add_columns(geojson_column.label("geojson")).cte("OBSERVATIONS")

    if output_format == "ungrouped_geom":
        query = select(obs_query.c.geojson, obs_query.c.obs_as_json)
    else:
        # Group geometries with main query
        grouped_properties = func.json_build_object(
            "observations", func.json_agg(obs_query.c.obs_as_json).label("observations")
        )
        query = select(obs_query.c.geojson, grouped_properties).group_by(obs_query.c.geojson)

    results = DB.session.execute(query)

    # Build final GeoJson
    geojson_features = []
    for geom_as_geojson, properties in results:
        geojson_features.append(
            Feature(
                geometry=json.loads(geom_as_geojson) if geom_as_geojson else None,
                properties=properties,
            )
        )
    return jsonify(FeatureCollection(geojson_features))


@routes.route("/vsynthese/<id_synthese>", methods=["GET"])
@permissions_required("R", module_code="SYNTHESE")
def get_one_synthese(permissions, id_synthese):
    """Get one synthese record for web app with all decoded nomenclature"""
    synthese_query = Synthese.join_nomenclatures().options(
        joinedload("dataset").options(
            selectinload("acquisition_framework").options(
                joinedload("creator"),
                joinedload("nomenclature_territorial_level"),
                joinedload("nomenclature_financing_type"),
            ),
        ),
        # Used to check the sensitivity after
        joinedload("nomenclature_sensitivity"),
    )
    ##################

    fields = [
        "dataset",
        "dataset.acquisition_framework",
        "dataset.acquisition_framework.bibliographical_references",
        "dataset.acquisition_framework.cor_af_actor",
        "dataset.acquisition_framework.cor_objectifs",
        "dataset.acquisition_framework.cor_territories",
        "dataset.acquisition_framework.cor_volets_sinp",
        "dataset.acquisition_framework.creator",
        "dataset.acquisition_framework.nomenclature_territorial_level",
        "dataset.acquisition_framework.nomenclature_financing_type",
        "dataset.cor_dataset_actor",
        "dataset.cor_dataset_actor.role",
        "dataset.cor_dataset_actor.organism",
        "dataset.cor_territories",
        "dataset.nomenclature_source_status",
        "dataset.nomenclature_resource_type",
        "dataset.nomenclature_dataset_objectif",
        "dataset.nomenclature_data_type",
        "dataset.nomenclature_data_origin",
        "dataset.nomenclature_collecting_method",
        "dataset.creator",
        "dataset.modules",
        "validations",
        "validations.validation_label",
        "validations.validator_role",
        "cor_observers",
        "cor_observers.organisme",
        "source",
        "habitat",
        "medias",
        "areas",
        "areas.area_type",
    ]

    # get reports info only if activated by admin config
    if "SYNTHESE" in current_app.config["SYNTHESE"]["ALERT_MODULES"]:
        fields.append("reports.report_type.type")
        synthese_query = synthese_query.options(
            lazyload(Synthese.reports).joinedload(TReport.report_type)
        )

    try:
        synthese = (
            db.session.execute(synthese_query.filter_by(id_synthese=id_synthese))
            .unique()
            .scalar_one()
        )
    except NoResultFound:
        raise NotFound()
    if not synthese.has_instance_permission(permissions=permissions):
        raise Forbidden()

    _, precise_permissions = split_blurring_precise_permissions(permissions)

    # If blurring permissions and obs sensitive.
    if (
        not synthese.has_instance_permission(precise_permissions)
        and synthese.nomenclature_sensitivity.cd_nomenclature != "0"
    ):
        # Use a cte to have the areas associated with the current id_synthese
        cte = select(CorAreaSynthese).where(CorAreaSynthese.id_synthese == id_synthese).cte()
        # Blurred area of the observation
        BlurredObsArea = aliased(LAreas)
        # Blurred area type of the observation
        BlurredObsAreaType = aliased(BibAreasTypes)
        # Types "larger" or equal in area hierarchy size that the blurred area type
        BlurredAreaTypes = aliased(BibAreasTypes)
        # Areas associates with the BlurredAreaTypes
        BlurredAreas = aliased(LAreas)

        # Inner join that retrieve the blurred area of the obs and the bigger areas
        # used for "Zonages" in Synthese. Need to have size_hierarchy from ref_geo
        inner = (
            sa.join(CorAreaSynthese, BlurredObsArea)
            .join(BlurredObsAreaType)
            .join(
                cor_sensitivity_area_type,
                cor_sensitivity_area_type.c.id_area_type == BlurredObsAreaType.id_type,
            )
            .join(
                BlurredAreaTypes,
                BlurredAreaTypes.size_hierarchy >= BlurredObsAreaType.size_hierarchy,
            )
            .join(BlurredAreas, BlurredAreaTypes.id_type == BlurredAreas.id_type)
            .join(cte, cte.c.id_area == BlurredAreas.id_area)
        )

        # Outer join to join CorAreaSynthese taking into account the sensitivity
        outer = (
            inner,
            sa.and_(
                Synthese.id_synthese == CorAreaSynthese.id_synthese,
                Synthese.id_nomenclature_sensitivity
                == cor_sensitivity_area_type.c.id_nomenclature_sensitivity,
            ),
        )

        synthese_query = (
            synthese_query.outerjoin(*outer)
            # contains_eager: to populate Synthese.areas directly
            .options(contains_eager(Synthese.areas.of_type(BlurredAreas)))
            .options(
                with_expression(
                    Synthese.the_geom_authorized,
                    func.coalesce(BlurredObsArea.geom_4326, Synthese.the_geom_4326),
                )
            )
            .order_by(BlurredAreaTypes.size_hierarchy)
        )
    else:
        synthese_query = synthese_query.options(
            lazyload("areas").options(
                joinedload("area_type"),
            ),
            with_expression(Synthese.the_geom_authorized, Synthese.the_geom_4326),
        )

    synthese = (
        db.session.execute(synthese_query.filter(Synthese.id_synthese == id_synthese))
        .unique()
        .scalar_one()
    )

    synthese_schema = SyntheseSchema(
        only=Synthese.nomenclature_fields + fields,
        exclude=["areas.geom"],
        as_geojson=True,
        feature_geometry="the_geom_authorized",
    )
    return synthese_schema.dump(synthese)


################################
########### EXPORTS ############
################################


@routes.route("/export_taxons", methods=["POST"])
@permissions_required("E", module_code="SYNTHESE")
def export_taxon_web(permissions):
    """Optimized route for taxon web export.

    .. :quickref: Synthese;

    This view is customisable by the administrator
    Some columns are mandatory: cd_ref

    POST parameters: Use a list of cd_ref (in POST parameters)
         to filter the v_synthese_taxon_for_export_view

    :query str export_format: str<'csv'>

    """
    taxon_view = GenericTable(
        tableName="v_synthese_taxon_for_export_view",
        schemaName="gn_synthese",
        engine=DB.engine,
    )
    columns = taxon_view.tableDef.columns

    # Test de conformité de la vue v_synthese_for_export_view
    try:
        assert hasattr(taxon_view.tableDef.columns, "cd_ref")
    except AssertionError as e:
        return (
            {
                "msg": """
                        View v_synthese_taxon_for_export_view
                        must have a cd_ref column \n
                        trace: {}
                        """.format(
                    str(e)
                )
            },
            500,
        )

    id_list = request.get_json()

    sub_query = (
        select(
            VSyntheseForWebApp.cd_ref,
            func.count(distinct(VSyntheseForWebApp.id_synthese)).label("nb_obs"),
            func.min(VSyntheseForWebApp.date_min).label("date_min"),
            func.max(VSyntheseForWebApp.date_max).label("date_max"),
        )
        .where(VSyntheseForWebApp.id_synthese.in_(id_list))
        .group_by(VSyntheseForWebApp.cd_ref)
    )

    synthese_query_class = SyntheseQuery(
        VSyntheseForWebApp,
        sub_query,
        {},
    )

    synthese_query_class.filter_query_all_filters(g.current_user, permissions)

    subq = synthese_query_class.query.alias("subq")

    query = select(*columns, subq.c.nb_obs, subq.c.date_min, subq.c.date_max).join(
        subq, subq.c.cd_ref == columns.cd_ref
    )

    return to_csv_resp(
        datetime.datetime.now().strftime("%Y_%m_%d_%Hh%Mm%S"),
        data=serializeQuery(db.session.execute(query).all(), query.column_descriptions),
        separator=";",
        columns=[db_col.key for db_col in columns] + ["nb_obs", "date_min", "date_max"],
    )


@routes.route("/export_observations", methods=["POST"])
@permissions_required("E", module_code="SYNTHESE")
def export_observations_web(permissions):
    """Optimized route for observations web export.

    .. :quickref: Synthese;

    This view is customisable by the administrator
    Some columns are mandatory: id_synthese, geojson and geojson_local to generate the exported files

    POST parameters: Use a list of id_synthese (in POST parameters) to filter the v_synthese_for_export_view

    :query str export_format: str<'csv', 'geojson', 'shapefiles', 'gpkg'>
    :query str export_format: str<'csv', 'geojson', 'shapefiles', 'gpkg'>

    """
    params = request.args
    # set default to csv
    export_format = params.get("export_format", "csv")
    view_name_param = params.get("view_name", "gn_synthese.v_synthese_for_export")
    # Test export_format
    if export_format not in current_app.config["SYNTHESE"]["EXPORT_FORMAT"]:
        raise BadRequest("Unsupported format")
    config_view = {
        "view_name": "gn_synthese.v_synthese_for_web_app",
        "geojson_4326_field": "geojson_4326",
        "geojson_local_field": "geojson_local",
    }
    # Test export view name is config params for security reason
    if view_name_param != "gn_synthese.v_synthese_for_export":
        try:
            config_view = next(
                _view
                for _view in current_app.config["SYNTHESE"]["EXPORT_OBSERVATIONS_CUSTOM_VIEWS"]
                if _view["view_name"] == view_name_param
            )
        except StopIteration:
            raise Forbidden("This view is not available for export")

    geojson_4326_field = config_view["geojson_4326_field"]
    geojson_local_field = config_view["geojson_local_field"]
    try:
        schema_name, view_name = view_name_param.split(".")
    except ValueError:
        raise BadRequest("view_name parameter must be a string with schema dot view_name")

    # get list of id synthese from POST
    id_list = request.get_json()

    # Get the SRID for the export
    local_srid = DB.session.execute(
        func.Find_SRID("gn_synthese", "synthese", "the_geom_local")
    ).scalar()

    blurring_permissions, precise_permissions = split_blurring_precise_permissions(permissions)

    # Get the view for export
    # Useful to have geom column so that they can be replaced by blurred geoms
    # (only if the user has sensitive permissions)
    export_view = GenericTableGeo(
        tableName=view_name,
        schemaName=schema_name,
        engine=DB.engine,
        geometry_field=None,
        srid=local_srid,
    )
    mandatory_columns = {"id_synthese", geojson_4326_field, geojson_local_field}
    if not mandatory_columns.issubset(set(map(lambda col: col.name, export_view.db_cols))):
        print(set(map(lambda col: col.name, export_view.db_cols)))
        raise BadRequest(
            f"The view {view_name} miss one of required columns {str(mandatory_columns)}"
        )

    # If there is no sensitive permissions => same path as before blurring implementation
    if not blurring_permissions:
        # Get the CTE for synthese filtered by user permissions
        synthese_query_class = SyntheseQuery(
            Synthese,
            select(Synthese.id_synthese),
            {},
        )
        synthese_query_class.filter_query_all_filters(g.current_user, permissions)
        cte_synthese_filtered = synthese_query_class.build_query().cte("cte_synthese_filtered")
        selectable_columns = [export_view.tableDef]
    else:
        # Use slightly the same process as for get_observations_for_web()
        # Add a where_clause to filter the id_synthese provided to reduce the
        # UNION queries
        where_clauses = [Synthese.id_synthese.in_(id_list)]
        blurred_geom_query, precise_geom_query = build_blurred_precise_geom_queries(
            filters={}, where_clauses=where_clauses
        )

        cte_synthese_filtered = build_allowed_geom_cte(
            blurring_permissions=blurring_permissions,
            precise_permissions=precise_permissions,
            blurred_geom_query=blurred_geom_query,
            precise_geom_query=precise_geom_query,
            limit=current_app.config["SYNTHESE"]["NB_MAX_OBS_EXPORT"],
        )

        # Overwrite geometry columns to compute the blurred geometry from the blurring cte
        columns_with_geom_excluded = [
            col
            for col in export_view.tableDef.columns
            if col.name
            not in [
                "geometrie_wkt_4326",  # FIXME: hardcoded column names?
                "x_centroid_4326",
                "y_centroid_4326",
                geojson_4326_field,
                geojson_local_field,
            ]
        ]
        # Recomputed the blurred geometries
        blurred_geom_columns = [
            func.st_astext(cte_synthese_filtered.c.geom).label("geometrie_wkt_4326"),
            func.st_x(func.st_centroid(cte_synthese_filtered.c.geom)).label("x_centroid_4326"),
            func.st_y(func.st_centroid(cte_synthese_filtered.c.geom)).label("y_centroid_4326"),
            func.st_asgeojson(cte_synthese_filtered.c.geom).label(geojson_4326_field),
            func.st_asgeojson(func.st_transform(cte_synthese_filtered.c.geom, local_srid)).label(
                geojson_local_field
            ),
        ]

        # Finally provide all the columns to be selected in the export query
        selectable_columns = columns_with_geom_excluded + blurred_geom_columns

    # Get the query for export
    export_query = (
        select(*selectable_columns)
        .select_from(
            export_view.tableDef.join(
                cte_synthese_filtered,
                cte_synthese_filtered.c.id_synthese == export_view.tableDef.columns["id_synthese"],
            )
        )
        .where(export_view.tableDef.columns["id_synthese"].in_(id_list))
    )

    # Get the results for export
    results = DB.session.execute(
        export_query.limit(current_app.config["SYNTHESE"]["NB_MAX_OBS_EXPORT"])
    )

    db_cols_for_shape = []
    columns_to_serialize = []
    # loop over synthese config to exclude columns if its default export
    for db_col in export_view.db_cols:
        if view_name_param == "gn_synthese.v_synthese_for_export":
            if db_col.key in current_app.config["SYNTHESE"]["EXPORT_COLUMNS"]:
                db_cols_for_shape.append(db_col)
                columns_to_serialize.append(db_col.key)
        else:
            # remove geojson fields of serialization
            if db_col.key not in [geojson_4326_field, geojson_local_field]:
                db_cols_for_shape.append(db_col)
                columns_to_serialize.append(db_col.key)

    file_name = datetime.datetime.now().strftime("%Y_%m_%d_%Hh%Mm%S")
    file_name = filemanager.removeDisallowedFilenameChars(file_name)

    if export_format == "csv":
        formated_data = [export_view.as_dict(d, fields=columns_to_serialize) for d in results]
        return to_csv_resp(file_name, formated_data, separator=";", columns=columns_to_serialize)
    elif export_format == "geojson":
        features = []
        for r in results:
            geometry = json.loads(getattr(r, geojson_4326_field))
            feature = Feature(
                geometry=geometry,
                properties=export_view.as_dict(r, fields=columns_to_serialize),
            )
            features.append(feature)
        results = FeatureCollection(features)
        return to_json_resp(results, as_file=True, filename=file_name, indent=4)
    else:
        try:
            dir_name, file_name = export_as_geo_file(
                export_format=export_format,
                export_view=export_view,
                db_cols=db_cols_for_shape,
                geojson_col=geojson_local_field,
                data=results,
                file_name=file_name,
            )
            return send_from_directory(dir_name, file_name, as_attachment=True)

        except GeonatureApiError as e:
            message = str(e)

        return render_template(
            "error.html",
            error=message,
            redirect=current_app.config["URL_APPLICATION"] + "/#/synthese",
        )


# TODO: Change the following line to set method as "POST" only ?
@routes.route("/export_metadata", methods=["GET", "POST"])
@permissions_required("E", module_code="SYNTHESE")
def export_metadata(permissions):
    """Route to export the metadata in CSV

    .. :quickref: Synthese;

    The table synthese is join with gn_synthese.v_metadata_for_export
    The column jdd_id is mandatory in the view gn_synthese.v_metadata_for_export

    TODO: Remove the following comment line ? or add the where clause for id_synthese in id_list ?
    POST parameters: Use a list of id_synthese (in POST parameters) to filter the v_synthese_for_export_view
    """
    filters = request.json if request.is_json else {}

    metadata_view = GenericTable(
        tableName="v_metadata_for_export",
        schemaName="gn_synthese",
        engine=DB.engine,
    )

    # Test de conformité de la vue v_metadata_for_export
    try:
        assert hasattr(metadata_view.tableDef.columns, "jdd_id")
    except AssertionError as e:
        return (
            {
                "msg": """
                        View v_metadata_for_export
                        must have a jdd_id column \n
                        trace: {}
                        """.format(
                    str(e)
                )
            },
            500,
        )

    q = select(distinct(VSyntheseForWebApp.id_dataset), metadata_view.tableDef)

    synthese_query_class = SyntheseQuery(
        VSyntheseForWebApp,
        q,
        filters,
    )
    synthese_query_class.add_join(
        metadata_view.tableDef,
        getattr(
            metadata_view.tableDef.columns,
            current_app.config["SYNTHESE"]["EXPORT_METADATA_ID_DATASET_COL"],
        ),
        VSyntheseForWebApp.id_dataset,
    )

    # Filter query with permissions (scope, sensitivity, ...)
    synthese_query_class.filter_query_all_filters(g.current_user, permissions)

    data = DB.session.execute(synthese_query_class.query)

    # Define the header of the csv file
    columns = [db_col.key for db_col in metadata_view.tableDef.columns]
    columns[columns.index("nombre_obs")] = "nombre_total_obs"

    # Retrieve the data to write in the csv file
    data = [metadata_view.as_dict(d) for d in data]
    for d in data:
        d["nombre_total_obs"] = d.pop("nombre_obs")

    return to_csv_resp(
        datetime.datetime.now().strftime("%Y_%m_%d_%Hh%Mm%S"),
        data=data,
        separator=";",
        columns=columns,
    )


@routes.route("/export_statuts", methods=["POST"])
@permissions_required("E", module_code="SYNTHESE")
def export_status(permissions):
    """Route to get all the protection status of a synthese search

    .. :quickref: Synthese;

    Get the CRUVED from 'R' action because we don't give observations X/Y but only statuts
    and to be consistent with the data displayed in the web interface.

    Parameters:
        - HTTP-GET: the same that the /synthese endpoint (all the filter in web app)
    """
    filters = request.json if request.is_json else {}

    # Initalize the select object
    query = select(
        distinct(VSyntheseForWebApp.cd_nom).label("cd_nom"),
        Taxref.cd_ref,
        Taxref.nom_complet,
        Taxref.nom_vern,
        TaxrefBdcStatutTaxon.rq_statut,
        TaxrefBdcStatutType.regroupement_type,
        TaxrefBdcStatutType.lb_type_statut,
        TaxrefBdcStatutText.cd_sig,
        TaxrefBdcStatutText.full_citation,
        TaxrefBdcStatutText.doc_url,
        TaxrefBdcStatutValues.code_statut,
        TaxrefBdcStatutValues.label_statut,
    )
    # Initialize SyntheseQuery class
    synthese_query = SyntheseQuery(VSyntheseForWebApp, query, filters)

    # Filter query with permissions
    synthese_query.filter_query_all_filters(g.current_user, permissions)

    # Add join
    synthese_query.add_join(Taxref, Taxref.cd_nom, VSyntheseForWebApp.cd_nom)
    synthese_query.add_join(
        CorAreaSynthese,
        CorAreaSynthese.id_synthese,
        VSyntheseForWebApp.id_synthese,
    )
    synthese_query.add_join(
        bdc_statut_cor_text_area, bdc_statut_cor_text_area.c.id_area, CorAreaSynthese.id_area
    )
    synthese_query.add_join(TaxrefBdcStatutTaxon, TaxrefBdcStatutTaxon.cd_ref, Taxref.cd_ref)
    synthese_query.add_join(
        TaxrefBdcStatutCorTextValues,
        TaxrefBdcStatutCorTextValues.id_value_text,
        TaxrefBdcStatutTaxon.id_value_text,
    )
    synthese_query.add_join_multiple_cond(
        TaxrefBdcStatutText,
        [
            TaxrefBdcStatutText.id_text == TaxrefBdcStatutCorTextValues.id_text,
            TaxrefBdcStatutText.id_text == bdc_statut_cor_text_area.c.id_text,
        ],
    )
    synthese_query.add_join(
        TaxrefBdcStatutType,
        TaxrefBdcStatutType.cd_type_statut,
        TaxrefBdcStatutText.cd_type_statut,
    )
    synthese_query.add_join(
        TaxrefBdcStatutValues,
        TaxrefBdcStatutValues.id_value,
        TaxrefBdcStatutCorTextValues.id_value,
    )

    # Build query
    query = synthese_query.build_query()

    # Set enable status texts filter
    query = query.where(TaxrefBdcStatutText.enable == True)

    protection_status = []
    data = DB.session.execute(query)

    for d in data:
        d = d._mapping
        row = OrderedDict(
            [
                ("cd_nom", d["cd_nom"]),
                ("cd_ref", d["cd_ref"]),
                ("nom_complet", d["nom_complet"]),
                ("nom_vern", d["nom_vern"]),
                ("type_regroupement", d["regroupement_type"]),
                ("type", d["lb_type_statut"]),
                ("territoire_application", d["cd_sig"]),
                ("intitule_doc", re.sub("<[^<]+?>", "", d["full_citation"])),
                ("code_statut", d["code_statut"]),
                ("intitule_statut", d["label_statut"]),
                ("remarque", d["rq_statut"]),
                ("url_doc", d["doc_url"]),
            ]
        )
        protection_status.append(row)
    export_columns = [
        "nom_complet",
        "nom_vern",
        "cd_nom",
        "cd_ref",
        "type_regroupement",
        "type",
        "territoire_application",
        "intitule_doc",
        "code_statut",
        "intitule_statut",
        "remarque",
        "url_doc",
    ]

    return to_csv_resp(
        datetime.datetime.now().strftime("%Y_%m_%d_%Hh%Mm%S"),
        protection_status,
        separator=";",
        columns=export_columns,
    )


######################################
########### OTHERS ROUTES ############
######################################


@routes.route("/general_stats", methods=["GET"])
@permissions_required("R", module_code="SYNTHESE")
@json_resp
def general_stats(permissions):
    """Return stats about synthese.

    .. :quickref: Synthese;

        - nb of observations
        - nb of distinct species
        - nb of distinct observer
        - nb of datasets
    """
    nb_allowed_datasets = db.session.scalar(
        select(func.count("*"))
        .select_from(TDatasets)
        .where(TDatasets.filter_by_readable().whereclause)
    )
    results = {"nb_allowed_datasets": nb_allowed_datasets}

    queries = {
        "nb_obs": select(Synthese.id_synthese),
        "nb_distinct_species": select(
            func.distinct(Synthese.cd_nom),
        ),
        "nb_distinct_observer": select(func.distinct(Synthese.observers)),
    }

    for key, query in queries.items():
        synthese_query = SyntheseQuery(Synthese, query, {})
        synthese_query.filter_query_with_permissions(g.current_user, permissions)
        results[key] = db.session.scalar(
            sa.select(func.count("*")).select_from(synthese_query.query)
        )

    data = {
        "nb_data": results["nb_obs"],
        "nb_species": results["nb_distinct_species"],
        "nb_observers": results["nb_distinct_observer"],
        "nb_dataset": results["nb_allowed_datasets"],
    }
    return data


## ############################################################################
## TAXON SHEET ROUTES
## ############################################################################

if app.config["SYNTHESE"]["ENABLE_TAXON_SHEETS"]:

    @routes.route("/taxon_stats/<int:cd_nom>", methods=["GET"])
    @permissions.check_cruved_scope("R", get_scope=True, module_code="SYNTHESE")
    @json_resp
    def taxon_stats(scope, cd_nom):
        """Return stats for a specific taxon"""

        area_type = request.args.get("area_type")

        if not area_type:
            raise BadRequest("Missing area_type parameter")

        # Ensure area_type is valid
        valid_area_types = (
            db.session.query(BibAreasTypes.type_code)
            .distinct()
            .filter(BibAreasTypes.type_code == area_type)
            .scalar()
        )
        if not valid_area_types:
            raise BadRequest("Invalid area_type")

        # Subquery to fetch areas based on area_type
        areas_subquery = (
            select(LAreas.id_area)
            .where(LAreas.id_type == BibAreasTypes.id_type, BibAreasTypes.type_code == area_type)
            .alias("areas")
        )
        cd_ref = db.session.scalar(select(Taxref.cd_ref).where(Taxref.cd_nom == cd_nom))
        taxref_cd_nom_list = db.session.scalars(
            select(Taxref.cd_nom).where(Taxref.cd_ref == cd_ref)
        )

        # Main query to fetch stats
        query = (
            select(
                [
                    func.count(distinct(Synthese.id_synthese)).label("observation_count"),
                    func.count(distinct(Synthese.observers)).label("observer_count"),
                    func.count(distinct(areas_subquery.c.id_area)).label("area_count"),
                    func.min(Synthese.altitude_min).label("altitude_min"),
                    func.max(Synthese.altitude_max).label("altitude_max"),
                    func.min(Synthese.date_min).label("date_min"),
                    func.max(Synthese.date_max).label("date_max"),
                ]
            )
            .select_from(
                sa.join(
                    Synthese,
                    CorAreaSynthese,
                    Synthese.id_synthese == CorAreaSynthese.id_synthese,
                )
                .join(areas_subquery, CorAreaSynthese.id_area == areas_subquery.c.id_area)
                .join(LAreas, CorAreaSynthese.id_area == LAreas.id_area)
                .join(BibAreasTypes, LAreas.id_type == BibAreasTypes.id_type)
            )
            .where(Synthese.cd_nom.in_(taxref_cd_nom_list))
        )

        synthese_query_obj = SyntheseQuery(Synthese, query, {})
        synthese_query_obj.filter_query_with_cruved(g.current_user, scope)
        result = DB.session.execute(synthese_query_obj.query)
        synthese_stats = result.fetchone()

        data = {
            "cd_ref": cd_nom,
            "observation_count": synthese_stats["observation_count"],
            "observer_count": synthese_stats["observer_count"],
            "area_count": synthese_stats["area_count"],
            "altitude_min": synthese_stats["altitude_min"],
            "altitude_max": synthese_stats["altitude_max"],
            "date_min": synthese_stats["date_min"],
            "date_max": synthese_stats["date_max"],
        }

        return data


@routes.route("/taxons_tree", methods=["GET"])
@login_required
@json_resp
def get_taxon_tree():
    """Get taxon tree.

    .. :quickref: Synthese;
    """
    taxon_tree_table = GenericTable(
        tableName="v_tree_taxons_synthese", schemaName="gn_synthese", engine=DB.engine
    )
    data = db.session.execute(select(taxon_tree_table.tableDef)).all()
    return [taxon_tree_table.as_dict(datum) for datum in data]


@routes.route("/taxons_autocomplete", methods=["GET"])
@login_required
@json_resp
def get_autocomplete_taxons_synthese():
    """Autocomplete taxon for web search (based on all taxon in Synthese).

    .. :quickref: Synthese;

    The request use trigram algorithm to get relevent results

    :query str search_name: the search name (use sql ilike statement and puts "%" for spaces)
    :query str regne: filter with kingdom
    :query str group2_inpn : filter with INPN group 2
    """
    search_name = request.args.get("search_name", "")
    query = (
        select(
            VMTaxrefListForautocomplete,
            func.similarity(VMTaxrefListForautocomplete.unaccent_search_name, search_name).label(
                "idx_trgm"
            ),
        )
        .distinct()
        .join(Synthese, Synthese.cd_nom == VMTaxrefListForautocomplete.cd_nom)
    )
    search_name = search_name.replace(" ", "%")
    query = query.where(
        VMTaxrefListForautocomplete.unaccent_search_name.ilike(
            func.unaccent("%" + search_name + "%")
        )
    )
    regne = request.args.get("regne")
    if regne:
        query = query.where(VMTaxrefListForautocomplete.regne == regne)

    group2_inpn = request.args.get("group2_inpn")
    if group2_inpn:
        query = query.where(VMTaxrefListForautocomplete.group2_inpn == group2_inpn)

    # FIXME : won't work now
    # query = query.order_by(
    #     desc(VMTaxrefListForautocomplete.cd_nom == VMTaxrefListForautocomplete.cd_ref)
    # )
    limit = request.args.get("limit", 20)
    data = db.session.execute(
        query.order_by(
            desc("idx_trgm"),
        ).limit(limit)
    ).all()
    return [d[0].as_dict() for d in data]


@routes.route("/sources", methods=["GET"])
@login_required
@json_resp
def get_sources():
    """Get all sources.

    .. :quickref: Synthese;
    """
    q = select(TSources)
    data = db.session.scalars(q).all()
    return [n.as_dict() for n in data]


@routes.route("/defaultsNomenclatures", methods=["GET"])
@login_required
def getDefaultsNomenclatures():
    """Get default nomenclatures

    .. :quickref: Synthese;

    :query str group2_inpn:
    :query str regne:
    :query int organism:
    """
    params = request.args
    group2_inpn = "0"
    regne = "0"
    organism = 0
    if "group2_inpn" in params:
        group2_inpn = params["group2_inpn"]
    if "regne" in params:
        regne = params["regne"]
    if "organism" in params:
        organism = params["organism"]
    types = request.args.getlist("mnemonique_type")

    query = select(
        distinct(DefaultsNomenclaturesValue.mnemonique_type),
        func.gn_synthese.get_default_nomenclature_value(
            DefaultsNomenclaturesValue.mnemonique_type, organism, regne, group2_inpn
        ),
    )
    if len(types) > 0:
        query = query.where(DefaultsNomenclaturesValue.mnemonique_type.in_(tuple(types)))
    data = db.session.execute(query).all()
    if not data:
        raise NotFound
    return jsonify(dict(data))


@routes.route("/color_taxon", methods=["GET"])
@login_required
def get_color_taxon():
    """Get color of taxon in areas (vue synthese.v_color_taxon_area).

    .. :quickref: Synthese;

    :query str code_area_type: Type area code (ref_geo.bib_areas_types.type_code)
    :query int id_area: Id of area (ref_geo.l_areas.id_area)
    :query int cd_nom: taxon code (taxonomie.taxref.cd_nom)
    Those three parameters can be multiples
    :returns: Array<dict<VColorAreaTaxon>>
    """
    params = request.args
    limit = int(params.get("limit", 100))
    page = params.get("page", 1, int)

    if "offset" in request.args:
        warn(
            "offset is deprecated, please use page for pagination (start at 1)", DeprecationWarning
        )
        page = (int(request.args["offset"]) / limit) + 1
    id_areas_type = params.getlist("code_area_type")
    cd_noms = params.getlist("cd_nom")
    id_areas = params.getlist("id_area")
    query = select(VColorAreaTaxon)
    if len(id_areas_type) > 0:
        query = query.join(LAreas, LAreas.id_area == VColorAreaTaxon.id_area).join(
            BibAreasTypes, BibAreasTypes.id_type == LAreas.id_type
        )
        query = query.where(BibAreasTypes.type_code.in_(tuple(id_areas_type)))
    if len(id_areas) > 0:
        # check if the join already done on l_areas
        if not is_already_joined(LAreas, query):
            query = query.join(LAreas, LAreas.id_area == VColorAreaTaxon.id_area)
        query = query.where(LAreas.id_area.in_(tuple(id_areas)))
    query = query.order_by(VColorAreaTaxon.cd_nom).order_by(VColorAreaTaxon.id_area)
    if len(cd_noms) > 0:
        query = query.where(VColorAreaTaxon.cd_nom.in_(tuple(cd_noms)))
    results = db.paginate(query, page=page, per_page=limit, error_out=False)

    return jsonify([d.as_dict() for d in results.items])


@routes.route("/taxa_count", methods=["GET"])
@login_required
@json_resp
def get_taxa_count():
    """
    Get taxa count in synthese filtering with generic parameters

    .. :quickref: Synthese;

    Parameters
    ----------
    id_dataset: `int` (query parameter)

    Returns
    -------
    count: `int`:
        the number of taxon
    """
    params = request.args

    query = (
        select(func.count(distinct(Synthese.cd_nom)))
        .select_from(Synthese)
        .where(Synthese.id_dataset == params["id_dataset"] if "id_dataset" in params else True)
    )
    return db.session.scalar(query)


@routes.route("/observation_count", methods=["GET"])
@login_required
@json_resp
def get_observation_count():
    """
    Get observations found in a given dataset

    .. :quickref: Synthese;

    Parameters
    ----------
    id_dataset: `int` (query parameter)

    Returns
    -------
    count: `int`:
        the number of observation

    """
    params = request.args

    query = select(func.count(Synthese.id_synthese)).select_from(Synthese)

    if "id_dataset" in params:
        query = query.where(Synthese.id_dataset == params["id_dataset"])

    return DB.session.execute(query).scalar_one()


@routes.route("/observations_bbox", methods=["GET"])
@login_required
def get_bbox():
    """
    Get bbox of observations

    .. :quickref: Synthese;

    Parameters
    -----------
    id_dataset: int: (query parameter)

    Returns
    -------
        bbox: `geojson`:
            the bounding box in geojson
    """
    params = request.args

    query = select(func.ST_AsGeoJSON(func.ST_Extent(Synthese.the_geom_4326)))

    if "id_dataset" in params:
        query = query.where(Synthese.id_dataset == params["id_dataset"])
    if "id_source" in params:
        query = query.where(Synthese.id_source == params["id_source"])
    data = db.session.execute(query).one()
    if data and data[0]:
        return Response(data[0], mimetype="application/json")
    return "", 204


@routes.route("/observation_count_per_column/<column>", methods=["GET"])
@login_required
def observation_count_per_column(column):
    """
    Get observations count group by a given column

    This function was used to count observations per dataset,
    but this usage have been replaced by
    TDatasets.synthese_records_count.
    Remove this function as it is very inefficient?
    """
    if column not in sa.inspect(Synthese).column_attrs:
        raise BadRequest(f"No column name {column} in Synthese")
    synthese_column = getattr(Synthese, column)
    stmt = (
        select(
            func.count(Synthese.id_synthese).label("count"),
            synthese_column.label(column),
        )
        .select_from(Synthese)
        .group_by(synthese_column)
    )
    return jsonify(DB.session.execute(stmt).fetchall())


@routes.route("/taxa_distribution", methods=["GET"])
@login_required
def get_taxa_distribution():
    """
    Get taxa distribution for a given dataset or acquisition framework
    and grouped by a certain taxa rank
    """

    id_dataset = request.args.get("id_dataset")
    id_af = request.args.get("id_af")
    id_source = request.args.get("id_source")

    rank = request.args.get("taxa_rank")
    if not rank:
        rank = "regne"

    try:
        rank = getattr(Taxref.__table__.columns, rank)
    except AttributeError:
        raise BadRequest("Rank does not exist")

    Taxref.group2_inpn

    query = (
        select(func.count(distinct(Synthese.cd_nom)), rank)
        .select_from(Synthese)
        .outerjoin(Taxref, Taxref.cd_nom == Synthese.cd_nom)
    )

    if id_dataset:
        query = query.where(Synthese.id_dataset == id_dataset)

    elif id_af:
        query = query.outerjoin(TDatasets, TDatasets.id_dataset == Synthese.id_dataset).where(
            TDatasets.id_acquisition_framework == id_af
        )
    # User can add id_source filter along with id_dataset or id_af
    if id_source is not None:
        query = query.where(Synthese.id_source == id_source)

    data = db.session.execute(query.group_by(rank)).all()
    return jsonify([{"count": d[0], "group": d[1]} for d in data])


@routes.route("/reports", methods=["POST"])
@permissions_required("R", module_code="SYNTHESE")
@json_resp
def create_report(permissions):
    """
    Create a report (e.g report) for a given synthese id

    Returns
    -------
        report: `json`:
            Every occurrence's report
    """
    session = DB.session
    data = request.get_json()
    if data is None:
        raise BadRequest("Empty request data")
    try:
        type_name = data["type"]
        id_synthese = data["item"]
        content = data["content"]
    except KeyError:
        raise BadRequest("Empty request data")
    if not id_synthese:
        raise BadRequest("id_synthese is missing from the request")
    if not type_name:
        raise BadRequest("Report type is missing from the request")
    if not content and type_name == "discussion":
        raise BadRequest("Discussion content is required")
    type_exists = BibReportsTypes.query.filter_by(type=type_name).first()
    if not type_exists:
        raise BadRequest("This report type does not exist")

    synthese = db.session.scalars(
        select(Synthese)
        .options(
            Load(Synthese).raiseload("*"),
            joinedload("nomenclature_sensitivity"),
            joinedload("cor_observers"),
            joinedload("digitiser"),
            joinedload("dataset"),
        )
        .filter_by(id_synthese=id_synthese)
        .limit(1),
    ).first()

    if not synthese:
        abort(404)

    if not synthese.has_instance_permission(permissions):
        raise Forbidden

    report_query = TReport.query.where(
        TReport.id_synthese == id_synthese,
        TReport.report_type.has(BibReportsTypes.type == type_name),
    )

    user_pin = TReport.query.where(
        TReport.id_synthese == id_synthese,
        TReport.report_type.has(BibReportsTypes.type == "pin"),
        TReport.id_role == g.current_user.id_role,
    )
    # only allow one alert by id_synthese
    if type_name in ["alert"]:
        alert_exists = report_query.one_or_none()
        if alert_exists is not None:
            raise Conflict("This type already exists for this id")
    if type_name in ["pin"]:
        pin_exist = user_pin.one_or_none()
        if pin_exist is not None:
            raise Conflict("This type already exists for this id")
    new_entry = TReport(
        id_synthese=id_synthese,
        id_role=g.current_user.id_role,
        content=content,
        creation_date=datetime.datetime.now(),
        id_type=type_exists.id_type,
    )
    session.add(new_entry)

    if type_name == "discussion":
        # Get the observers of the observation
        observers = {observer.id_role for observer in synthese.cor_observers}
        # Get the users that commented the observation
        commenters = {
            report.id_role
            for report in report_query.where(
                TReport.id_role.notin_({synthese.id_digitiser} | observers)
            ).distinct(TReport.id_role)
        }
        # The id_roles are the Union between observers and commenters
        id_roles = observers | commenters | {synthese.id_digitiser}
        # Remove the user that just commented the obs not to notify him/her
        id_roles.discard(g.current_user.id_role)
        notify_new_report_change(
            synthese=synthese, user=g.current_user, id_roles=id_roles, content=content
        )
    session.commit()


def notify_new_report_change(synthese, user, id_roles, content):
    if not synthese.id_digitiser:
        return
    dispatch_notifications(
        code_categories=["OBSERVATION-COMMENT"],
        id_roles=id_roles,
        title="Nouveau commentaire sur une observation",
        url=(
            current_app.config["URL_APPLICATION"]
            + "/#/synthese/occurrence/"
            + str(synthese.id_synthese)
        ),
        context={"synthese": synthese, "user": user, "content": content},
    )


@routes.route("/reports/<int:id_report>", methods=["PUT"])
@login_required
@json_resp
def update_content_report(id_report):
    """
    Modify a report (e.g report) for a given synthese id

    Returns
    -------
        report: `json`:
            Every occurrence's report
    """
    data = request.json
    session = DB.session
    idReport = data["idReport"]
    row = TReport.query.get_or_404(idReport)
    if row.user != g.current.user:
        raise Forbidden
    row.content = data["content"]
    session.commit()


@routes.route("/reports", methods=["GET"])
@permissions_required("R", module_code="SYNTHESE")
def list_all_reports(permissions):
    # Parameters
    type_name = request.args.get("type")
    orderby = request.args.get("orderby", "creation_date")
    sort = request.args.get("sort")
    page = request.args.get("page", 1, int)
    per_page = request.args.get("per_page", 10, int)
    my_reports = request.args.get("my_reports", "false").lower() == "true"

    # Start query
    query = (
        sa.select(TReport, User.nom_complet)
        .join(User, TReport.id_role == User.id_role)
        .options(
            joinedload(TReport.report_type).load_only(
                BibReportsTypes.type, BibReportsTypes.id_type
            ),
            joinedload(TReport.synthese).load_only(
                Synthese.cd_nom,
                Synthese.nom_cite,
                Synthese.observers,
                Synthese.date_min,
                Synthese.date_max,
            ),
            joinedload(TReport.user).load_only(User.nom_role, User.prenom_role),
        )
    )
    # Verify and filter by type
    if type_name:
        type_exists = db.session.scalar(
            sa.exists(BibReportsTypes).where(BibReportsTypes.type == type_name).select()
        )
        if not type_exists:
            raise BadRequest("This report type does not exist")
        query = query.where(TReport.report_type.has(BibReportsTypes.type == type_name))

    # Filter by id_role for 'pin' type only or if my_reports is true
    if type_name == "pin" or my_reports:
        query = query.where(
            or_(
                TReport.id_role == g.current_user.id_role,
                TReport.id_synthese.in_(
                    select(TReport.id_synthese).where(TReport.id_role == g.current_user.id_role)
                ),
                TReport.synthese.has(Synthese.id_digitiser == g.current_user.id_role),
                TReport.synthese.has(
                    Synthese.cor_observers.any(User.id_role == g.current_user.id_role)
                ),
            )
        )

    # On vérifie les permissions en lecture sur la synthese
    synthese_query = select(Synthese.id_synthese).select_from(Synthese)
    synthese_query_obj = SyntheseQuery(Synthese, synthese_query, {})
    synthese_query_obj.filter_query_with_permissions(g.current_user, permissions)
    cte_synthese = synthese_query_obj.query.cte("cte_synthese")
    query = query.where(TReport.id_synthese == cte_synthese.c.id_synthese)

    SORT_COLUMNS = {
        "user.nom_complet": User.nom_complet,
        "content": TReport.content,
        "creation_date": TReport.creation_date,
    }

    # Determine the sorting
    if orderby in SORT_COLUMNS:
        sort_column = SORT_COLUMNS[orderby]
        if sort == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))
    else:
        raise BadRequest("Bad orderby")

    # Pagination
    paginated_results = db.paginate(query, page=page, per_page=per_page)

    result = []

    for report in paginated_results.items:
        report_dict = {
            "id_report": report.id_report,
            "id_synthese": report.id_synthese,
            "id_role": report.id_role,
            "report_type": {
                "type": report.report_type.type,
                "id_type": report.report_type.id_type,
            },
            "content": report.content,
            "deleted": report.deleted,
            "creation_date": report.creation_date,
            "user": {"nom_complet": report.user.nom_complet},
            "synthese": {
                "cd_nom": report.synthese.cd_nom,
                "nom_cite": report.synthese.nom_cite,
                "observers": report.synthese.observers,
                "date_min": report.synthese.date_min,
                "date_max": report.synthese.date_max,
            },
        }
        result.append(report_dict)

    response = {
        "total": paginated_results.total,
        "page": paginated_results.page,
        "per_page": paginated_results.per_page,
        "items": result,
    }
    return jsonify(response)


@routes.route("/reports/<int:id_synthese>", methods=["GET"])
@permissions_required("R", module_code="SYNTHESE")
def list_reports(permissions, id_synthese):
    type_name = request.args.get("type")

    synthese = db.get_or_404(Synthese, id_synthese)
    if not synthese.has_instance_permission(permissions):
        raise Forbidden

    query = sa.select(TReport).where(TReport.id_synthese == id_synthese)

    # Verify and filter by type
    if type_name:
        type_exists = db.session.scalar(
            sa.exists(BibReportsTypes).where(BibReportsTypes.type == type_name).select()
        )
        if not type_exists:
            raise BadRequest("This report type does not exist")
        query = query.where(TReport.report_type.has(BibReportsTypes.type == type_name))

    # Filter by id_role for 'pin' type only
    if type_name == "pin":
        query = query.where(TReport.id_role == g.current_user.id_role)

    # Join the User table
    query = query.options(
        joinedload(TReport.user).load_only(User.nom_role, User.prenom_role),
        joinedload(TReport.report_type),
    )

    return ReportSchema(many=True, only=["+user.nom_role", "+user.prenom_role"]).dump(
        db.session.scalars(query).all()
    )


@routes.route("/reports/<int:id_report>", methods=["DELETE"])
@login_required
@json_resp
def delete_report(id_report):
    reportItem = TReport.query.get_or_404(id_report)
    # alert control to check cruved - allow validators only
    if reportItem.report_type.type in ["alert"]:
        permissions = get_permissions(module_code="SYNTHESE", action_code="R")
        if not reportItem.synthese.has_instance_permission(permissions):
            raise Forbidden("Permission required to delete this report !")
    # only owner could delete a report for pin and discussion
    if reportItem.id_role != g.current_user.id_role and reportItem.report_type.type in [
        "discussion",
        "pin",
    ]:
        raise Forbidden
    # discussion control to don't delete but tag report as deleted only
    if reportItem.report_type.type == "discussion":
        reportItem.content = ""
        reportItem.deleted = True
    else:
        DB.session.delete(reportItem)
    DB.session.commit()


@routes.route("/log", methods=["get"])
@login_required
def list_synthese_log_entries() -> dict:
    """Get log history from synthese

    Parameters
    ----------

    Returns
    -------
    dict
        log action list
    """
    # FIXME SQLA 2
    deletion_entries = SyntheseLogEntry.query.options(
        load_only(
            SyntheseLogEntry.id_synthese,
            SyntheseLogEntry.last_action,
            SyntheseLogEntry.meta_last_action_date,
        )
    )
    create_update_entries = Synthese.query.with_entities(
        Synthese.id_synthese,
        db.case(
            (Synthese.meta_create_date < Synthese.meta_update_date, "U"),
            else_="I",
        ).label("last_action"),
        func.coalesce(Synthese.meta_update_date, Synthese.meta_create_date).label(
            "meta_last_action_date"
        ),
    )
    query = deletion_entries.union(create_update_entries)

    # Filter
    try:
        query = query.filter_by_params(request.args)
    except ValueError as exc:
        raise BadRequest(*exc.args) from exc

    # Sort
    try:
        query = query.sort(request.args.getlist("sort"))
    except ValueError as exc:
        raise BadRequest(*exc.args) from exc

    # Paginate
    limit = request.args.get("limit", type=int, default=50)
    page = request.args.get("page", type=int, default=1)
    results = query.paginate(page=page, per_page=limit, error_out=False)

    return jsonify(
        {
            "items": [item.as_dict() for item in results.items],
            "total": results.total,
            "limit": limit,
            "page": page,
        }
    )
