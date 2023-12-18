from Digitraffic_To_SQLite_functions import (create_connection, collect_ships_locations,
                                             append_table, delete_duplicate_rows, 
                                             delete_old)
from Draw_Map_functions import load_data, draw_map
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

# Set cutoff for last known locations to draw/update
# (locations updated before will not be drawn/updated)
# NOTE: Python timestamps in seconds, digitraffic in milliseconds
# since_hrs = 1
since_hrs = int(sys.argv[1])

since = datetime.now() - timedelta(hours=since_hrs, minutes=5)
since = floor(since.timestamp()*1000)

# database = "AIS.sqlite"
database = sys.argv[2]
db_connection = create_connection(database)

# Update locations in database
locations_df = collect_ships_locations(latitude, longitude, distance, since)
append_table(db_connection, locations_df, "locations")
delete_duplicate_rows(db_connection, "locations", ", ".join(list(locations_df.columns)))

# Delete sufficiently old location data from database
time_cutoff_dt = datetime.now() - timedelta(days=14)
time_cutoff_ts = floor(time_cutoff_dt.timestamp()*1000)
delete_old(db_connection, "locations", "locUpdateTimestamp", time_cutoff_ts)

# Set initial map center
map_longitude = 23.29
map_latitude = 59.837
map_center = [map_latitude, map_longitude]

# Draw new map
# Aranda = 230145000
# Augusta = 230149210
vip_ships = [230145000, 230149210]

ships_df = load_data(db_connection, since) # NOTE: Assumes each ship only has one row in meta table
map = draw_map(map_center, ships_df, vip_ships, db_connection)
db_connection.close()

# Save the map to a file
# root_dir = "/opt/usr/local/www/html/glider"
# map_filename = "ais_map.html"
root_dir = sys.argv[3]
map_filename = sys.argv[4]
map.save(f"{root_dir}/{map_filename}")

# .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/update_locations.py" 1 ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite" ".../FMI Gliders/AIS Map/Map Data" AIS_map.html