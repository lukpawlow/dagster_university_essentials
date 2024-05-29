
from dagster_duckdb import DuckDBResource
import requests
import pandas as pd
from . import constants
from dagster import asset, MaterializeResult, MetadataValue, AssetExecutionContext
from ..partitions import monthly_partition


@asset(
    partitions_def=monthly_partition,
    group_name='raw_files'
)
def taxi_trips_file(context: AssetExecutionContext) -> MaterializeResult:
    """
      The raw parquet files for the taxi trips dataset. Sourced from the NYC Open Data portal.
    """
    partition_date_str = context.asset_partition_key_for_output()
    month_to_fetch = partition_date_str[:-3]
    raw_trips = requests.get(
        f"https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month_to_fetch}.parquet"
    )

    with open(constants.TAXI_TRIPS_TEMPLATE_FILE_PATH.format(month_to_fetch), "wb") as output_file:
        output_file.write(raw_trips.content)

    num_rows = len(pd.read_parquet(constants.TAXI_TRIPS_TEMPLATE_FILE_PATH.format(month_to_fetch)))

    return MaterializeResult(
        metadata={
            'Number of records': MetadataValue.int(num_rows)
        }
)


@asset(
    group_name="raw_files",
)
def taxi_zones_file() -> MaterializeResult:
    """
    The raw CSV file for the taxi zones dataset. Sourced from the NYC Open Data portal.
    """
    raw_taxi_zones = requests.get(
        "https://data.cityofnewyork.us/api/views/755u-8jsi/rows.csv?accessType=DOWNLOAD"
    )

    with open(constants.TAXI_ZONES_FILE_PATH, "wb") as output_file:
        output_file.write(raw_taxi_zones.content)

    num_rows = len(pd.read_csv(constants.TAXI_ZONES_FILE_PATH))
    
    return MaterializeResult(
        metadata={
            'Number of records': MetadataValue.int(num_rows)
        }
    )

@asset(
    deps=["taxi_trips_file"],
    partitions_def=monthly_partition,
    group_name='ingested'
)
def taxi_trips(context, database: DuckDBResource):
    """
      The raw taxi trips dataset, loaded into a DuckDB database, partitioned by month.
    """
    partition_date_str = context.asset_partition_key_for_output()
    month_to_fetch = partition_date_str[:-3]

    sql_query = f"""
        create table if not exists trips (
        vendor_id integer, pickup_zone_id integer, dropoff_zone_id integer,
        rate_code_id double, payment_type integer, dropoff_datetime timestamp,
        pickup_datetime timestamp, trip_distance double, passenger_count double,
        total_amount double, partition_date varchar
      );
    
      delete from trips where partition_date = '{month_to_fetch}';

      insert into trips
      select
        VendorID, PULocationID, DOLocationID, RatecodeID, payment_type, tpep_dropoff_datetime,
        tpep_pickup_datetime, trip_distance, passenger_count, total_amount, '{month_to_fetch}' as partition_date
      from '{constants.TAXI_TRIPS_TEMPLATE_FILE_PATH.format(month_to_fetch)}';
    """

    with database.get_connection() as conn:
        conn.execute(sql_query)


@asset(
    deps=["taxi_zones_file"],
    group_name='ingested'
)
def taxi_zones(database: DuckDBResource):
    """
      The raw taxi zone dasaset, loaded into a DuckDB
    """
    sql_query = f"""
        create or replace table zones as (
            select
                LocationID as zone_id,
                zone as zone,
                borough as borough,
                the_geom as geometry
            from '{constants.TAXI_ZONES_FILE_PATH}'
        );    
    """

    with database.get_connection() as conn:
        conn.execute(sql_query)

