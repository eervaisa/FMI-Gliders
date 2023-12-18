from Digitraffic_To_SQLite_functions import (create_connection, update_meta_table, 
                                             get_latest_meta_update_timestamp)
import sys

# NOTE: Required downloads: 
# UpdatedPub150.csv from https://msi.nga.mil/Publications/WPI 
# code-list_csv.csv from https://datahub.io/core/un-locode
# Make sure you're in the same directory, 
# or adjust their paths in Digitraffic_To_SQLite_functions.py

# database = "AIS.sqlite"
database = sys.argv[1]
db_connection = create_connection(database)

# Updates metadata for known mmsis and adds new rows for new mmsis since last update
update_meta_table(db_connection, get_latest_meta_update_timestamp(db_connection))

# NOTE: Instead of updating existing metadata, you can also simply append by using
""" from datetime import datetime, timedelta
from math import floor
since = datetime.now() - timedelta(hours=12, minutes=0)
since = floor(since.timestamp()*1000)
meta_df = collect_ships_meta(since)
append_table(db_connection, meta_df, "meta")
delete_duplicate_rows(db_connection, "meta", ", ".join(list(meta_df.columns)))"""
# NOTE: This however gets ALL ships that changed metadata - using locations to get 
#       each mmsi separately probably shouldn't be used due to being very slow 
#       (>0.5s per mmsi)

db_connection.close()

# .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/update_meta.py" ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite"