from Digitraffic_To_SQLite_functions import (create_connection, update_meta_table, 
                                            collect_ships_locations, append_table, 
                                            delete_duplicate_rows)
from datetime import datetime, timedelta
from math import floor
import sys

# NOTE: Required downloads: 
# UpdatedPub150.csv from https://msi.nga.mil/Publications/WPI 
# code-list_csv.csv from https://datahub.io/core/un-locode
# Make sure you're in the same directory, 
# or adjust their paths in Digitraffic_To_SQLite_functions.py

latitude = 60
longitude = 20
distance = 700

# since_hrs = 12
since_hrs = int(sys.argv[1])

# NOTE: Python timestamps in seconds, digitraffic in milliseconds
since = datetime.now() - timedelta(hours=since_hrs, minutes=0)
since = floor(since.timestamp()*1000)

# database = "AIS.sqlite"
database = sys.argv[2]
db_connection = create_connection(database)

# NOTE: Only initialize once when creating database.
#       Initializing more than once should not cause errors, but is a waste of resources
initialization_timestamp = floor(datetime.strptime("2018-01-01", 
                                                   "%Y-%m-%d").timestamp()*1000)
update_meta_table(db_connection, initialization_timestamp)

locations_df = collect_ships_locations(latitude, longitude, distance, since)

append_table(db_connection, locations_df, "locations")
delete_duplicate_rows(db_connection, "locations", ", ".join(list(locations_df.columns)))

db_connection.close()

# .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Data/initialize_ais_database.py" 12 ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite"