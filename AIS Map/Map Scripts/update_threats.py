from Digitraffic_To_SQLite_functions import (create_connection, 
                                             collect_specific_ships_locations, 
                                             get_recent_threat_mmsi_list,
                                             append_table, delete_duplicate_rows)
from Draw_Map_functions import load_data, draw_map
from datetime import datetime, timedelta
from math import floor
import sys

# NOTE: Required downloads: 
# UpdatedPub150.csv from https://msi.nga.mil/Publications/WPI 
# code-list_csv.csv from https://datahub.io/core/un-locode
# Make sure you're in the same directory, 
# or adjust their paths in Digitraffic_To_SQLite_functions.py

# database = "AIS.sqlite"
database = sys.argv[2]
db_connection = create_connection(database)

# Set cutoff for what "recent" means:
# recommend using a value slightly higher than timeframe between this script being run again
# (e.g. if run every 10 mins, set to 15)
recency_cutoff_mins = int(sys.argv[3])
recency_cutoff = datetime.now() - timedelta(minutes=recency_cutoff_mins)
recency_cutoff_timestamp = floor(recency_cutoff.timestamp()*1000)

mmsi_list = get_recent_threat_mmsi_list(db_connection, recency_cutoff_timestamp)

# Aranda = 230145000
# Augusta = 230149210
vip_ships = [230145000, 230149210]

mmsi_list += vip_ships

if(len(mmsi_list) > 0):
    # Update locations of threats in database
    locations_df = collect_specific_ships_locations(mmsi_list)
    append_table(db_connection, locations_df, "locations")
    delete_duplicate_rows(db_connection, "locations", ", ".join(list(locations_df.columns)))

    # Set cutoff for last known locations to draw 
    # (locations updated before will not be drawn)
    since_hrs = int(sys.argv[1])
    since = datetime.now() - timedelta(hours=since_hrs, minutes=5)
    since = floor(since.timestamp()*1000)

    # Set initial map center
    map_longitude = 23.29
    map_latitude = 59.837
    map_center = [map_latitude, map_longitude]

    # Draw new map
    ships_df = load_data(db_connection, since) # NOTE: Assumes each ship only has one row in meta table
    map = draw_map(map_center, ships_df, vip_ships, db_connection)
    
    # Save the map to a file
    # root_dir = "/opt/usr/local/www/html/glider"
    # map_filename = "ais_map.html"
    root_dir = sys.argv[4]
    map_filename = sys.argv[5]
    map.save(f"{root_dir}/{map_filename}")

db_connection.close()

# .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/update_threats.py" 1 ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite" 15 ".../FMI Gliders/AIS Map/Map Data" AIS_map.html