import pandas as pd
import sqlite3
from sqlite3 import Error
from datetime import datetime, timedelta

import requests
import json

import folium
import folium.plugins as plugins
import altair as alt
from branca.element import Template, MacroElement

import math
import numpy as np

import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

from urllib.error import HTTPError

from Digitraffic_To_SQLite_functions import (update_meta_table, 
                                             get_latest_meta_update_timestamp, 
                                             classify_regions, 
                                             append_table, delete_duplicate_rows)

#############################
#    Database interaction   #
#############################

def create_connection(db_file):
    '''Create a database connection to a SQLite database'''

    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        print(e)
    
    return conn

def check_missing_meta(db_connection, ships_df):
    '''Check if any metadata is missing and update if necessary'''

    no_meta = ships_df["metaUpdateTimestamp"].isna()
    if(any(no_meta)):
        no_meta_ships = ships_df[no_meta.values]["mmsi"]
        no_meta_ships_string = ", ".join(no_meta_ships.apply(str))

        # Update meta table from API
        update_meta_table(db_connection, get_latest_meta_update_timestamp(db_connection))

        # Query missing metadata
        query = f"SELECT * FROM meta WHERE mmsi IN ({no_meta_ships_string})"
        meta_df = pd.read_sql_query(query, db_connection)

        if(meta_df.empty):
            print("Some metadata still missing after update, try again later")
            return ships_df

        # Make mmsi into the index for updating
        meta_df.set_index('mmsi', inplace = True)
        ships_df.set_index('mmsi', inplace = True)

        # Fill missing data
        ships_df.update(meta_df)

        # Make mmsi into a column again
        ships_df.reset_index(inplace = True)

    return ships_df

def load_data(db_connection, since):
    '''Load and merge data from a SQLite database into a dataframe'''

    # Set limit for previous path length from current time
    path_since = since - timedelta(hours=3).seconds*1000

    # Query data after path_since for ships that had an update after since
    query = ("SELECT * FROM locations "
            "LEFT JOIN meta ON locations.mmsi = meta.mmsi "
            f"WHERE locations.mmsi IN "
                "(SELECT mmsi from locations "
               f"WHERE locUpdateTimestamp > {since}) "
            f"AND locUpdateTimestamp > {path_since}")

    ships_df = pd.read_sql_query(query, db_connection)

    ships_df = ships_df.loc[:,~ships_df.columns.duplicated()] # If mmsi column duplicates from missing values in meta, drop the extra column    

    # Create a column for the path in a new dataframe
    ship_paths_df = ships_df[["mmsi", "latitude", "longitude"]].copy()
    ship_paths_df.drop_duplicates(inplace = True)
    ship_paths_df["coords"] = ship_paths_df[["latitude", "longitude"]].values.tolist()
    ship_paths_df = ship_paths_df.groupby("mmsi").apply(lambda row: list(row["coords"]), include_groups=False).reset_index()
    ship_paths_df.rename(columns = {0: "path"}, inplace = True)

    # Take only latest location and add path column
    ships_df = ships_df.loc[ships_df.groupby(["mmsi"])["locUpdateTimestamp"].idxmax()]
    ships_df = ships_df.merge(ship_paths_df, how='left')

    # Check for missing metadata and add it if necessary
    ships_df = check_missing_meta(db_connection, ships_df)

    # Fix formatting and naming of time columns
    ships_df["metaUpdatetime"]  = pd.to_datetime(ships_df["metaUpdateTimestamp"],unit="ms")
    ships_df["locUpdatetime"]   = pd.to_datetime(ships_df["locUpdateTimestamp"], unit="ms")

    # Drop unnecessary columns
    # ships_df = ships_df.drop(["metaUpdateTimestamp", "locUpdateTimestamp", "rownum"], axis=1)
    ships_df = ships_df.drop(["metaUpdateTimestamp", "locUpdateTimestamp"], axis=1)

    return ships_df

def save_dangerous_ship_data(ships_df, glider_name, glider_latest_loc, db_connection):
    '''Update SQLite database with dangerous ship data'''

    # TODO: Consider if:
    #       We should convert time back to timestamp for database interaction
    #       Retrieve and save rows from before threat classification (when still "yellow")
    #       We want more data about glider
    #       Currently chance for duplicating same ship for multiple gliders, and if that matters

    dangerous_ships = ships_df.loc[(ships_df['threat_class'].isin([2,3,5]))].copy()

    if(not dangerous_ships.empty):

        # Set the colours we would draw the markers with for easier readability
        dangerous_ships["class_colour"] = "#8ED6FF"
        dangerous_ships.loc[(dangerous_ships['threat_class'] == 1), 
                            "class_colour"] = "yellow"
        dangerous_ships.loc[(dangerous_ships['threat_class'] == 2), 
                            "class_colour"] = "orange"
        dangerous_ships.loc[(dangerous_ships['threat_class'] == 3), 
                            "class_colour"] = "red"
        dangerous_ships.loc[(dangerous_ships['threat_class'] == 4), 
                            "class_colour"] = "grey"
        dangerous_ships.loc[(dangerous_ships['threat_class'] == 5), 
                            "class_colour"] = "purple"

        dangerous_ships['glider_name'] = glider_name
        dangerous_ships['glider_latest_lat'] = glider_latest_loc[0]
        dangerous_ships['glider_latest_lon'] = glider_latest_loc[1]
        dangerous_ships.drop(columns=['path', 'range', 'tooltip_html', 'threat_class', 'max_threat_class'], inplace=True)

        append_table(db_connection, dangerous_ships, "threats")
        delete_duplicate_rows(db_connection, "threats", ", ".join(list(dangerous_ships.columns)))

    return

#############################
#  Glider data interaction  #
#############################

def read_web_json(url):
    '''Read json-file from url'''

    try:
        r = requests.get(url)
        data = r.json()
    except Exception as e:
        print(e)
        return {}
    return(data)

def read_json(file):
    '''Read local json-file'''
    try:
        f = open(file, "r")
    except IOError as e:
        print(e)
        return {}
    else:
        data = json.loads(f.read())
        f.close()
    return(data)

def load_glider_sensors(interesting_sensors):
    '''Read data from glider'''

    pathData = read_json('../Map Data/Gliders/JSONs/current_positions.json')
    glider_names = list(pathData.keys())

    gliders_df = pd.DataFrame()
    for glider_name in glider_names:
        glider_df = pd.DataFrame.from_dict(pathData[glider_name])
        glider_df["glider_name"] = str.capitalize(glider_name)
        gliders_df = pd.concat([gliders_df, glider_df], ignore_index=True)
    
    if(gliders_df.empty):
        return None, gliders_df, interesting_sensors

    gliders_df["datetime"] = pd.to_datetime(gliders_df["datetime"], format='%Y-%m-%dT%H:%M:%SZ')

    # Explode nested dicts into columns
    gliders_df = gliders_df.join(pd.DataFrame(gliders_df.pop('location').values.tolist()))

    sensors_df = pd.DataFrame(gliders_df.pop('sensors').values.tolist())
    
    # Use only sensors also in dataframe:
    interesting_sensors = list(set(sensors_df.columns).intersection(set(interesting_sensors)))

    sensors_df = sensors_df[interesting_sensors]
    gliders_df = gliders_df.join(sensors_df)

    return glider_names, gliders_df, interesting_sensors

def load_glider_waypoints(glider_names, gliders_latest_loc):
    '''Read waypoint plan data'''

    glider_waypoints = read_json('../Map Data/Gliders/JSONs/glider_waypoints.json')
    wpt_glider_names = list(glider_waypoints.keys())
    gliders_wpt_df = pd.DataFrame()
    
    for glider_name in glider_names:
        # Add data into dataframe
        glider_wpt_df = pd.DataFrame()
        if(glider_name in wpt_glider_names):
            glider_wpt_df['longitude'] = [coords[0] for coords in glider_waypoints[glider_name]]
            glider_wpt_df['latitude']  = [coords[1] for coords in glider_waypoints[glider_name]]
            glider_wpt_df['glider_name'] = str.capitalize(glider_name)
        else:
            glider_wpt_df = gliders_latest_loc.loc[gliders_latest_loc["glider_name"] == str.capitalize(glider_name), 
                                               ["glider_name", "latitude", "longitude"]].copy()
            glider_wpt_df.reset_index(drop=True, inplace=True)

        gliders_wpt_df = pd.concat([gliders_wpt_df, glider_wpt_df], ignore_index=True)

    return gliders_wpt_df
    

def load_glider_data():
    ''' Load glider data and reformat for map drawing'''

    interesting_sensors = ["m_battery", 
                    "m_coulomb_amphr_total", 
                    "m_digifin_leakdetect_reading", 
                    "m_lithium_battery_relative_charge"]

    glider_names, gliders_df, interesting_sensors = load_glider_sensors(interesting_sensors)

    if (gliders_df.empty):
        return None, interesting_sensors

    gliders_latest_loc = gliders_df.loc[gliders_df.groupby(["glider_name"])["datetime"].idxmax()]

    gliders_wpt_df = load_glider_waypoints(glider_names, gliders_latest_loc)

    gliders_wpt_df = classify_regions(gliders_wpt_df, "latitude", "longitude", "glider_region")

    glider_names = [str.capitalize(glider_name) for glider_name in glider_names]

    gliders_regions = gliders_wpt_df[["glider_name", "glider_region"]].drop_duplicates()

    glider_data = {"glider_names":       glider_names,
                   "gliders_df":         gliders_df,
                   "gliders_wpt_df":     gliders_wpt_df,
                   "gliders_latest_loc": gliders_latest_loc,
                   "gliders_regions":    gliders_regions}

    return glider_data, interesting_sensors

#############################
#  Coordinate calculations  #
#############################

def haversine_distance(point1, point2):
    '''Haversine distance between two points, points in gps coordinates'''
    
    R = 6373.0
    lat1 = math.radians(point1[0])
    lon1 = math.radians(point1[1])
    lat2 = math.radians(point2[0])
    lon2 = math.radians(point2[1])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = (math.sin(dlat/2))**2 + math.cos(lat1) * math.cos(lat2) * (math.sin(dlon/2))**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = R * c
    return distance

def get_endpoint(lat1,lon1,bearing,dist):
    '''Find end point with start coordinates, bearing & distance'''
    
    R = 6371                     #Radius of the Earth

    d = dist
    
    brng = math.radians(bearing) #Convert degrees to radians
    
    lat1 = math.radians(lat1)    #Current lat point converted to radians
    lon1 = math.radians(lon1)    #Current long point converted to radians

    lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng)*math.sin(d/R)*math.cos(lat1),math.cos(d/R)-math.sin(lat1)*math.sin(lat2))
    lat2 = math.degrees(lat2)
    lon2 = math.degrees(lon2)
    
    return [lat2,lon2]

def get_path(coords, sog, cog, rot):
    '''Find path coordinates based on speed, course and rotation'''
    # sog is speed over ground in knots (= 1.852 km/h). Most ships move at 10-20 knots.
    # rot = 4.733*SQRT(ROT[IND]) where ROT[IND] is the Rate of Turn degrees per minute. +(-)127 == >(<-)720 deg/min
    
    path = [coords]
    # If ship's speed is undefined or zero, just give up
    if(sog==0 | pd.isna(sog)):
        return [path,0]

    interval_duration = 1  # Minutes
    path_duration     = 60 # Minutes
    latitude  = coords[0]
    longitude = coords[1]
    bearing = cog
    rotation = 0 if pd.isna(rot) else rot

    interval_distance = sog/(60/interval_duration)*1.852                        # Convert nautical miles to km (knots to km/h) and duration from min to h
    interval_rotation = (rotation/4.733)**2*interval_duration*np.sign(rotation) # Convert to deg/min

    radius = interval_distance*(path_duration/interval_duration)*1000 # Leaflet's L.Circle uses meters (as float) for radius
    if(pd.isna(radius)):
        radius = 0

    # If ship rotates too fast or course is undefined, simply draw a circle based on speed
    if((abs(interval_rotation) >= 90) | pd.isna(cog)):
        return path, radius

    for i in range(path_duration//interval_duration-1):
        path.append(get_endpoint(latitude,longitude,bearing,interval_distance))
        latitude = path[i+1][0]
        longitude = path[i+1][1]

        # Limit turning to a U-turn
        if(round(abs(bearing - cog),2) >= 180):
            bearing = (cog + 180) % 360
        else:
            bearing = bearing + interval_rotation

    return path, radius

#############################
#    Ship data processing   #
#############################

def translate_ship_types(ships_df):
    '''Translate ship type to string'''
    
    ships_df["shipTypeString"] = "None"
    ships_df.loc[(ships_df['shipType'] >= 20) & (ships_df['shipType'] <= 29), "shipTypeString"] = "Wing in ground"
    ships_df.loc[(ships_df['shipType'] == 30),                                "shipTypeString"] = "Fishing"
    ships_df.loc[(ships_df['shipType'] >= 31) & (ships_df['shipType'] <= 32), "shipTypeString"] = "Towing"
    ships_df.loc[(ships_df['shipType'] == 33),                                "shipTypeString"] = "Dredging or underwater ops"
    ships_df.loc[(ships_df['shipType'] == 34),                                "shipTypeString"] = "Diving ops"
    ships_df.loc[(ships_df['shipType'] == 35),                                "shipTypeString"] = "Military ops"
    ships_df.loc[(ships_df['shipType'] == 36),                                "shipTypeString"] = "Sailing"
    ships_df.loc[(ships_df['shipType'] == 37),                                "shipTypeString"] = "Pleasure Craft"
    ships_df.loc[(ships_df['shipType'] >= 40) & (ships_df['shipType'] <= 49), "shipTypeString"] = "High speed craft"
    ships_df.loc[(ships_df['shipType'] == 50),                                "shipTypeString"] = "Pilot Vessel"
    ships_df.loc[(ships_df['shipType'] == 51),                                "shipTypeString"] = "Search and Rescue vessel"
    ships_df.loc[(ships_df['shipType'] == 52),                                "shipTypeString"] = "Tug"
    ships_df.loc[(ships_df['shipType'] == 53),                                "shipTypeString"] = "Port Tender"
    ships_df.loc[(ships_df['shipType'] == 54),                                "shipTypeString"] = "Anti-pollution equipment"
    ships_df.loc[(ships_df['shipType'] == 55),                                "shipTypeString"] = "Law Enforcement"
    ships_df.loc[(ships_df['shipType'] >= 56) & (ships_df['shipType'] <= 57), "shipTypeString"] = "Spare - Local Vessel"
    ships_df.loc[(ships_df['shipType'] == 58),                                "shipTypeString"] = "Law Enforcement"
    ships_df.loc[(ships_df['shipType'] == 59),                                "shipTypeString"] = "Noncombatant"
    ships_df.loc[(ships_df['shipType'] >= 60) & (ships_df['shipType'] <= 69), "shipTypeString"] = "Passenger"
    ships_df.loc[(ships_df['shipType'] >= 70) & (ships_df['shipType'] <= 79), "shipTypeString"] = "Cargo"
    ships_df.loc[(ships_df['shipType'] >= 80) & (ships_df['shipType'] <= 89), "shipTypeString"] = "Tanker"
    ships_df.loc[(ships_df['shipType'] >= 90) & (ships_df['shipType'] <= 99), "shipTypeString"] = "Other"
    
    return ships_df

def process_no_gliders_ship_data(ships_df):
    '''Prepare data for drawing ship markers when there are no active gliders'''

    # Predict ship movement
    # NOTE: GeoPandas uses LonLat, so all intersect checks have to as well
    # ships_df[['path', 'range']]  = ships_df.apply(lambda row: get_path([row['latitude'],row['longitude']],row['sog'],row['cog'],row['rot']), axis=1, result_type='expand')
    ships_df[['predicted_path', 'range']]  = ships_df.apply(lambda row: get_path([row['latitude'],row['longitude']],row['sog'],row['cog'],row['rot']), axis=1, result_type='expand')
    ships_df['path'] = ships_df['path'] + ships_df['predicted_path']
    ships_df.drop(columns=['predicted_path'], inplace=True)
    ship_ranges = gpd.GeoDataFrame(ships_df, geometry=gpd.points_from_xy(ships_df.longitude, ships_df.latitude), crs="EPSG:4979") # Map projection units in degrees
    ship_ranges = ship_ranges.to_crs("EPSG:3857")         # Map projection units in meters for setting circle radius
    ship_ranges = ship_ranges.buffer(ships_df['range'])
    ship_ranges = ship_ranges.to_crs("EPSG:4979")         # Map projection units in degrees for testing intersection

    # Translate ship type to string
    ships_df = translate_ship_types(ships_df)

    # For consistency in presentation
    ships_df[["name","callSign","shipTypeString","destination","eta"]] = ships_df[["name","callSign","shipTypeString","destination","eta"]].fillna("")

    ships_df['tooltip_html'] = ships_df.apply(lambda ship: '</span></p><p style="text-align:left;">'.join(
            ['<p style="text-align:left;"> ' + 
             'Name: <span style="float:right;">'          + ship['name'],
             'Callsign: <span style="float:right;">'      + ship['callSign'],
             'Ship type: <span style="float:right;">'     + ship['shipTypeString'],
             'Draught (m): <span style="float:right;">'   + str(ship['draught']/10).replace('nan',''),
             'Location: <span style="float:right;">'      + str(round(ship['latitude'], 3)) + " / " + str(round(ship['longitude'], 3)),
             'Speed (knots): <span style="float:right;">' + str(ship['sog']).replace('nan',''),
             'Course (deg): <span style="float:right;">'  + str(ship['cog']).replace('nan',''),
             'Destination: <span style="float:right;">'   + ship['destination'],
             'ETA: <span style="float:right;">'           + ship['eta'].replace('T',' '),
             'Last updated: <span style="float:right;">'  + ship['locUpdatetime'].strftime("%Y-%m-%d %H:%M:%S").replace('NaT','') + 
             "</p>"]), axis=1)

    # After creating tooltips but before creating markers we want to fill NAs
    ships_df[['cog', 'sog']] = ships_df[['cog', 'sog']].fillna(0) 
    
    return ships_df

def classify_ships(ships_df, ship_ranges, vip_ships, glider_latest_loc, glider_regions, glider_wpt_line):
    '''Classify ships based on threat'''

    ships_df['distance_from_glider'] = ships_df.apply(lambda ship: haversine_distance([ship['latitude'],ship['longitude']], glider_latest_loc), axis=1)

    # Default/unclassified
    ships_df['threat_class'] = 0

    # Ships in - or with destination in - the same region as glider
    ships_df.loc[ships_df[['shipRegion', 
                          'destinationOneRegion', 
                          'destinationTwoRegion', 
                          'destinationThreeRegion']].isin(glider_regions).any(axis=1), "threat_class"] = 1

    # Check for ships going through glider regions
    if("Bothnian Sea" in glider_regions):
        ships_df.loc[(ships_df['shipRegion'].isin(["Baltic Sea", "Archipelago Sea", "Gulf of Finland", "Saimaa and Laatokka"])) & 
                     (ships_df[['destinationOneRegion', 
                                'destinationTwoRegion', 
                                'destinationThreeRegion']].isin(["Bothnian Bay"]).any(axis=1)), 
                    "threat_class"] = 1
        ships_df.loc[(ships_df['shipRegion'].isin(["Bothnian Bay"])) & 
                     (ships_df[['destinationOneRegion', 
                                'destinationTwoRegion', 
                                'destinationThreeRegion']].isin(["Baltic Sea", "Archipelago Sea", "Gulf of Finland", "Saimaa and Laatokka"]).any(axis=1)), 
                    "threat_class"] = 1
    
    if("Archipelago Sea" in glider_regions):
        ships_df.loc[(ships_df['shipRegion'].isin(["Baltic Sea", "Gulf of Finland", "Saimaa and Laatokka"])) & 
                     (ships_df[['destinationOneRegion', 
                                'destinationTwoRegion', 
                                'destinationThreeRegion']].isin(["Bothnian Bay", "Bothnian Sea"]).any(axis=1)), 
                    "threat_class"] = 1
        ships_df.loc[(ships_df['shipRegion'].isin(["Bothnian Bay", "Bothnian Sea"])) & 
                     (ships_df[['destinationOneRegion', 
                                'destinationTwoRegion', 
                                'destinationThreeRegion']].isin(["Baltic Sea", "Gulf of Finland", "Saimaa and Laatokka"]).any(axis=1)), 
                    "threat_class"] = 1
        
    if("Gulf of Finland" in glider_regions):
        ships_df.loc[(ships_df['shipRegion'].isin(["Saimaa and Laatokka"])) & 
                     (ships_df[['destinationOneRegion', 
                                'destinationTwoRegion', 
                                'destinationThreeRegion']].isin(["Baltic Sea", "Archipelago Sea", "Bothnian Bay", "Bothnian Sea"]).any(axis=1)), 
                    "threat_class"] = 1
        ships_df.loc[(ships_df['shipRegion'].isin(["Baltic Sea", "Archipelago Sea", "Bothnian Bay", "Bothnian Sea"])) & 
                     (ships_df[['destinationOneRegion', 
                                'destinationTwoRegion', 
                                'destinationThreeRegion']].isin(["Saimaa and Laatokka"]).any(axis=1)), 
                    "threat_class"] = 1

    # Ships that intersect glider plan
    # TODO: Consider marking only those that also don't intersect past path?
    #       dangerous with sharp turns though...
    ships_df.loc[(ships_df['range'] > 0) & (ship_ranges.intersects(glider_wpt_line)), "threat_class"] = 2

    # Ships whose range intersects glider's location
    ships_df.loc[(ships_df['range'] > 0) & (ships_df['distance_from_glider']*1000 < ships_df['range']), "threat_class"] = 3

    # Stationary ships
    ships_df.loc[(ships_df['sog'] == 0), "threat_class"] = 4

    # Ships within 10km
    ships_df.loc[(ships_df['distance_from_glider'] < 10), "threat_class"] = 5

    # VIP ships
    ships_df.loc[(ships_df['mmsi'].isin(vip_ships)), "threat_class"] = 99

    # Save the highest threat class so far for map drawing
    ships_df.loc[(ships_df['max_threat_class'] < ships_df['threat_class']), 
                 "max_threat_class"] = ships_df['threat_class']
    
    return ships_df

def process_ship_data(ships_df, glider_data, vip_ships, db_connection):
    '''Prepare data for drawing ship markers'''

    # Predict ship movement
    # NOTE: GeoPandas uses LonLat, so all intersect checks have to as well
    # ships_df[['path', 'range']]  = ships_df.apply(lambda row: get_path([row['latitude'],row['longitude']],row['sog'],row['cog'],row['rot']), axis=1, result_type='expand')
    ships_df[['predicted_path', 'range']]  = ships_df.apply(lambda row: get_path([row['latitude'],row['longitude']],row['sog'],row['cog'],row['rot']), axis=1, result_type='expand')
    ships_df['path'] = ships_df['path'] + ships_df['predicted_path']
    ships_df.drop(columns=['predicted_path'], inplace=True)
    ship_ranges = gpd.GeoDataFrame(ships_df, geometry=gpd.points_from_xy(ships_df.longitude, ships_df.latitude), crs="EPSG:4326") # Map projection units in degrees
    ship_ranges = ship_ranges.to_crs("EPSG:32634")         # Map projection units in meters for setting circle radius
    ship_ranges = ship_ranges.buffer(ships_df['range'])
    ship_ranges = ship_ranges.to_crs("EPSG:4326")         # Map projection units in degrees for testing intersection

    # Unpack glider_data dict for readability
    glider_names       = glider_data["glider_names"]
    gliders_regions    = glider_data["gliders_regions"]
    gliders_wpt_df     = glider_data["gliders_wpt_df"]
    gliders_latest_loc = glider_data["gliders_latest_loc"]

    # Translate ship type to string
    ships_df = translate_ship_types(ships_df)

    # For consistency in presentation
    ships_df[["name","callSign","shipTypeString","destination","eta"]] = ships_df[["name","callSign","shipTypeString","destination","eta"]].fillna("")

    ships_df['tooltip_html'] = ships_df.apply(lambda ship: '</span></p><p style="text-align:left;">'.join(
            ['<p style="text-align:left;"> ' + 
             'Name: <span style="float:right;">'          + ship['name'],
             'Callsign: <span style="float:right;">'      + ship['callSign'],
             'Ship type: <span style="float:right;">'     + ship['shipTypeString'],
             'Draught (m): <span style="float:right;">'   + str(ship['draught']/10).replace('nan',''),
             'Location: <span style="float:right;">'      + str(round(ship['latitude'], 3)) + " / " + str(round(ship['longitude'], 3)),
             'Speed (knots): <span style="float:right;">' + str(ship['sog']).replace('nan',''),
             'Course (deg): <span style="float:right;">'  + str(ship['cog']).replace('nan',''),
             'Destination: <span style="float:right;">'   + ship['destination'],
             'ETA: <span style="float:right;">'           + ship['eta'].replace('T',' '),
             'Last updated: <span style="float:right;">'  + ship['locUpdatetime'].strftime("%Y-%m-%d %H:%M:%S").replace('NaT','') + 
             "</p>"]), axis=1)

    ships_df['max_threat_class'] = 0

    for glider_name in glider_names:
        glider_latest_loc = gliders_latest_loc[["latitude","longitude"]].loc[gliders_latest_loc["glider_name"] == glider_name].values.tolist()[0]
        glider_regions = list(gliders_regions["glider_region"].loc[gliders_regions["glider_name"] == glider_name])
        glider_wpt_df = gliders_wpt_df.loc[gliders_wpt_df["glider_name"] == glider_name]

        # NOTE: GeoPandas uses LonLat, so all intersect checks have to as well
        glider_wpt_line = glider_wpt_df[["longitude", "latitude"]].values.tolist()
        if(len(glider_wpt_line) > 1):
            glider_wpt_line = LineString(glider_wpt_line)
        else:
            glider_wpt_line = Point(glider_wpt_line)

        ships_df = classify_ships(ships_df, ship_ranges, vip_ships, glider_latest_loc, glider_regions, glider_wpt_line)
        
        # Write dangerous ships into a sqlite table
        save_dangerous_ship_data(ships_df, glider_name, glider_latest_loc, db_connection)

    # Set the colours we want to draw the markers with
    ships_df["max_class_colour"] = "#8ED6FF"
    ships_df.loc[(ships_df['max_threat_class'] == 1), 
                 "max_class_colour"] = "yellow"
    ships_df.loc[(ships_df['max_threat_class'] == 2), 
                 "max_class_colour"] = "orange"
    ships_df.loc[(ships_df['max_threat_class'] == 3), 
                 "max_class_colour"] = "red"
    ships_df.loc[(ships_df['max_threat_class'] == 4), 
                 "max_class_colour"] = "grey"
    ships_df.loc[(ships_df['max_threat_class'] == 5), 
                 "max_class_colour"] = "purple"
    ships_df.loc[(ships_df['max_threat_class'] == 99), 
                 "max_class_colour"] = "#26f018"
    
    # Drop now unnecessary classification columns
    ships_df.drop(columns=['threat_class', 'max_threat_class'], inplace=True)

    # After creating tooltips but before creating markers we want to fill NAs
    ships_df[['cog', 'sog']] = ships_df[['cog', 'sog']].fillna(0) 
    return ships_df

#############################
#        Map drawing        #
#############################

def add_no_gliders_ship_markers(map, ships_df, vip_ships):
    '''Add markers for ships on the map when there are no active gliders'''

    # Create layers for ship markers
    # For performance reasons we don't show all at once by default
    baltic_sea_ship_layer      = folium.map.FeatureGroup(name = "Baltic Sea", show = False)
    bothnian_bay_ship_layer    = folium.map.FeatureGroup(name = "Bothnian Bay", show = False)
    bothnian_sea_ship_layer    = folium.map.FeatureGroup(name = "Bothnian Sea")
    archipelago_sea_ship_layer = folium.map.FeatureGroup(name = "Archipelago Sea")
    gulf_of_finland_ship_layer = folium.map.FeatureGroup(name = "Gulf of Finland")
    saimaa_laatokka_ship_layer = folium.map.FeatureGroup(name = "Saimaa and Laatokka", show = False)
    vip_ship_layer             = folium.map.FeatureGroup(name = "VIP ships")

    for ship in ships_df.itertuples(index=False, name='Ship'):
        color = "#8ED6FF"
        if(ship.mmsi in vip_ships):
            color = "#26f018"
        iframe = folium.IFrame(html=ship.tooltip_html, width=300, height=350)
        popup = folium.Popup(html=iframe, max_width=300)
        marker = plugins.BoatMarker([ship.latitude, ship.longitude], popup=popup, color=color,
                                     heading=ship.cog, pathCoords=ship.path, circleRadius=ship.range)
        if(ship.mmsi in vip_ships):
            marker.add_to(vip_ship_layer)
        elif(ship.shipRegion == "Bothnian Bay"):
            marker.add_to(bothnian_bay_ship_layer)
        elif(ship.shipRegion == "Bothnian Sea"):
            marker.add_to(bothnian_sea_ship_layer)    
        elif(ship.shipRegion == "Archipelago Sea"):
            marker.add_to(archipelago_sea_ship_layer)
        elif(ship.shipRegion == "Gulf of Finland"):
            marker.add_to(gulf_of_finland_ship_layer)
        elif(ship.shipRegion == "Saimaa and Laatokka"):
            marker.add_to(saimaa_laatokka_ship_layer)
        else:
            marker.add_to(baltic_sea_ship_layer)

    # Add the layers to the map
    baltic_sea_ship_layer.add_to(map)
    bothnian_bay_ship_layer.add_to(map)
    bothnian_sea_ship_layer.add_to(map)
    archipelago_sea_ship_layer.add_to(map)
    gulf_of_finland_ship_layer.add_to(map)
    saimaa_laatokka_ship_layer.add_to(map)
    vip_ship_layer.add_to(map)

    # Add links to ant-path and semi-circle js for on-click effects to work
    link = folium.JavascriptLink("https://cdn.jsdelivr.net/npm/leaflet-ant-path@1.3.0/dist/leaflet-ant-path.js")
    map.get_root().html.add_child(link)

    link = folium.JavascriptLink("https://cdn.jsdelivr.net/npm/leaflet-semicircle@2.0.4/Semicircle.min.js")
    map.get_root().html.add_child(link)

    return map

def add_on_click_functionality(map):
    '''Edit javascript to add on-click events to ship markers'''

    # Modify Marker template to include the onClick event
    
    click_template = """
                    {% macro script(this, kwargs) %}
                        var {{ this.get_name() }} = L.boatMarker(
                            {{ this.location|tojson }},
                            {{ this.options|tojson }}
                        ).addTo({{ this._parent.get_name() }}).on('click', onClick).on('dblclick', onDblClick);
                        {% if this.wind_heading is not none -%}
                        {{ this.get_name() }}.setHeadingWind(
                            {{ this.heading }},
                            {{ this.wind_speed }},
                            {{ this.wind_heading }}
                        );
                        {% else -%}
                        {{this.get_name()}}.setHeading({{this.heading}});
                        {% endif -%}
                    {% endmacro %}
                    """

    # Change template to custom template
    plugins.BoatMarker._template = folium.map.Template(click_template)

    map_id = map.get_name()

    # Extensions of circle and polyline are used here so they can be removed on click without 
    # removing all circles and polylines (glider paths and ranges)
    click_js = f"""function onClick(e) {{                
                                    
                    var coords = e.target.options.pathCoords;

                    var circle_radius = e.target.options.circleRadius;
                    var ship_location = [e.latlng.lat, e.latlng.lng];


                    var ship_range = L.semiCircle(ship_location, {{
                    radius: circle_radius,
                    fill: true,
                    color: 'red',
                    fillColor: 'orange',
                    fillOpacity: 0.3,
                    startAngle: 360,
                    stopAngle: 360

                    }}).on('dblclick', onDblClick);

                    
                    
                    var ant_path = L.polyline.antPath(coords, {{
                    "delay": 400,
                    "dashArray": [
                        10,
                        20
                    ],
                    "weight": 5,
                    "color": "#0000FF",
                    "pulseColor": "#FFFFFF",
                    "paused": false,
                    "reverse": false,
                    "hardwareAccelerated": true
                    }}); 


                    {map_id}.eachLayer(function(layer){{
                    if (layer instanceof L.Polyline.AntPath)
                        {{ {map_id}.removeLayer(layer) }}
                        }});

                    {map_id}.eachLayer(function(layer){{
                    if (layer instanceof L.SemiCircle)
                        {{ {map_id}.removeLayer(layer) }}
                        }});
                        
                    ship_range.addTo({map_id});
                    ant_path.addTo({map_id});
                    }}

                    function onDblClick(e) {{
                        {map_id}.eachLayer(function(layer){{
                    if (layer instanceof L.SemiCircle)
                        {{ {map_id}.removeLayer(layer) }}
                        }});
                    }}
                    """
                    
    e = folium.Element(click_js)
    html = map.get_root()
    html.script.add_child(e)
     
    return map

def extrapolate_variables(glider_df, extrapolation_variables, extrapolation_targets):
    '''Perform linear extrapolation of given variables'''
    # Calculate the differences between rows in datetime and battery_variable columns
    gradient_df = glider_df[extrapolation_variables + ["datetime"]].diff()

    # Create the dataframe used to hold extrapolated data
    last_datetime = glider_df["datetime"].loc[glider_df["datetime"].idxmax()]
    extrapolated_data = pd.DataFrame([np.full(len(extrapolation_variables), np.nan)], columns=extrapolation_variables)
    extrapolated_data = extrapolated_data.add_suffix("_extrapolated")
    extrapolated_data["datetime"] = last_datetime

    for i,variable in enumerate(extrapolation_variables):
        # Determine latest non-NA value for variable and its datetime
        last_value = glider_df[variable].loc[glider_df[variable].last_valid_index()]
        last_value_datetime = glider_df["datetime"].loc[glider_df[variable].last_valid_index()]

        extrapolation_target = extrapolation_targets[i]
        # Calculate the difference per second for each row
        gradient_df[f"{variable}_per_second"] = gradient_df[variable]/gradient_df["datetime"].dt.seconds
        # Take the weighted average per second difference from rows within timeframe ending at last valid variable data point
        # making sure not to include NAs
        gradient_timeframe = timedelta(hours=12)
        gradient_timeframe_idx = ((glider_df["datetime"] > last_value_datetime - gradient_timeframe) & 
                                  (gradient_df[f"{variable}_per_second"].notna()))

        if(len(gradient_timeframe_idx) > 0):
            avg_gradient = np.average(gradient_df[gradient_timeframe_idx][f"{variable}_per_second"], 
                                      weights=gradient_df[gradient_timeframe_idx]["datetime"].dt.seconds)
        else:
            avg_gradient = np.nan

        if(np.isnan(avg_gradient) | 
           (avg_gradient*(extrapolation_target-last_value) <= 0)): # Gradient == 0 or different sign from expected gradient
            continue # Extrapolated values are NaN

        secs_to_target = (extrapolation_target-last_value)/avg_gradient
        secs_to_target = np.ceil(secs_to_target)

        extrapolated_datetime = last_value_datetime + timedelta(seconds=secs_to_target)
        extrapolated_value = last_value + secs_to_target*avg_gradient

        # Add the starting point for the extrapolated graph
        if(extrapolated_data.datetime.isin([last_value_datetime]).any()): # If startpoint datetime already in dataframe
            extrapolated_data.loc[extrapolated_data["datetime"] == last_value_datetime, f"{variable}_extrapolated"] = last_value
        else:                                                             # If startpoint datetime not yet in dataframe
            new_row = {"datetime":last_value_datetime, f"{variable}_extrapolated":last_value}
            extrapolated_data = pd.concat([extrapolated_data, pd.DataFrame([new_row])], ignore_index=True)
            
        # Add the end point for the extrapolated graph
        if(extrapolated_data.datetime.isin([extrapolated_datetime]).any()): # If endpoint datetime already in dataframe
            extrapolated_data.loc[extrapolated_data["datetime"] == extrapolated_datetime, f"{variable}_extrapolated"] = extrapolated_value
        else:                                                               # If endpoint datetime not yet in dataframe
            new_row = {"datetime":extrapolated_datetime, f"{variable}_extrapolated":extrapolated_value}
            extrapolated_data = pd.concat([extrapolated_data, pd.DataFrame([new_row])], ignore_index=True)
    
    # Since Altair has issues with columns that are mostly missing values, we need to extrapolate all variables to the last datetime
    extrapolated_data.sort_values(by=["datetime"], inplace=True)
    extrapolated_data.set_index("datetime", inplace=True)
    extrapolated_data.interpolate(method='time', inplace=True, limit_direction="forward", limit_area="inside")
    extrapolated_data.reset_index(inplace=True)

    return extrapolated_data

def extrapolate_glider_battery(glider_name, glider_df, interesting_sensors):
    '''Extrapolate glider battery level for plotting'''
    # If the glider is named Koskelo, use m_lithium_battery_relative_charge. Otherwise m_battery
    battery_variable = "m_battery"
    battery_unit = "V"
    battery_extrapolation_target = 10
    battery_domain = [battery_extrapolation_target,16]
    
    if(glider_name == "Koskelo"): 
        battery_variable = "m_lithium_battery_relative_charge"
        battery_unit = "%"
        battery_extrapolation_target = 10
        battery_domain = [battery_extrapolation_target, 100]   

    coulomb_extrapolation_target = 160
    coulomb_domain = [0, coulomb_extrapolation_target]

    extrapolation_variables = [battery_variable, "m_coulomb_amphr_total"]
    extrapolation_targets = [battery_extrapolation_target, coulomb_extrapolation_target]

    extrapolated_data = extrapolate_variables(glider_df, extrapolation_variables, extrapolation_targets)

    # Create the dataframe used in plotting
    plot_df = glider_df[["datetime"]+interesting_sensors].copy()
    plot_df = plot_df.merge(extrapolated_data, how="outer")

    return plot_df, battery_variable, battery_unit, battery_domain, coulomb_domain

def adjust_domains(domain, end_point_values):
    '''Adjust domain ranges based on last and first two values'''
    # If non-outlier end point value is outside domain, then expand domain
    # Check domain minimum
    if(abs(end_point_values[0] - end_point_values[1]) < 1): # If neither is an outlier
        if(min(end_point_values[0:2]) < domain[0]): # If the smaller value is smaller than domain minimum
            domain[0] = min(end_point_values[0:2])
    else:                                           # If one is an outlier
        if(max(end_point_values[0:2]) < domain[0]): # If the larger value is smaller than domain minimum
            domain[0] = max(end_point_values[0:2])  

    # Check domain maximum
    if(abs(end_point_values[2] - end_point_values[3]) < 1): # If neither is an outlier
        if(max(end_point_values[2:4]) > domain[1]): # If the larger value is larger than domain minimum
            domain[1] = max(end_point_values[2:4])
    else:                                           # If one is an outlier
        if(min(end_point_values[2:4]) > domain[1]): # If the smaller value is larger than domain minimum
            domain[1] = min(end_point_values[2:4])
    
    return domain

def adjust_glider_popup_chart_domains(glider_df, battery_variable, battery_domain, coulomb_domain):
    '''Make sure all relevant glider data gets shown'''
    # battery_variable
    highest_battery_value_index = glider_df[battery_variable].first_valid_index()
    second_highest_battery_value_index = glider_df[battery_variable].loc[highest_battery_value_index+1:].first_valid_index()

    lowest_battery_value_index = glider_df[battery_variable].last_valid_index()
    second_lowest_battery_value_index = glider_df[battery_variable].loc[:lowest_battery_value_index-1].last_valid_index()

    battery_end_values = glider_df[battery_variable].loc[[lowest_battery_value_index, second_lowest_battery_value_index, 
                                                          second_highest_battery_value_index, highest_battery_value_index]].tolist()

    battery_domain = adjust_domains(battery_domain, battery_end_values)

    # m_coulomb_amphr_total
    highest_coulomb_value_index = glider_df["m_coulomb_amphr_total"].last_valid_index()
    second_highest_coulomb_value_index = glider_df["m_coulomb_amphr_total"].loc[:highest_coulomb_value_index-1].last_valid_index()

    lowest_coulomb_value_index = glider_df["m_coulomb_amphr_total"].first_valid_index()
    second_lowest_coulomb_value_index = glider_df["m_coulomb_amphr_total"].loc[lowest_coulomb_value_index+1:].first_valid_index()

    coulomb_end_values = glider_df["m_coulomb_amphr_total"].loc[[lowest_coulomb_value_index, second_lowest_coulomb_value_index, 
                                                          second_highest_coulomb_value_index, highest_coulomb_value_index]].tolist()

    coulomb_domain = adjust_domains(coulomb_domain, coulomb_end_values)

    return battery_domain, coulomb_domain

def create_glider_popup_chart(glider_name, glider_df, interesting_sensors):
    '''Create the chart used in glider popup'''
    plot_df, battery_variable, battery_unit, battery_domain, coulomb_domain = extrapolate_glider_battery(glider_name, glider_df, interesting_sensors)

    date_range = [min(glider_df.datetime),max(glider_df.datetime)]
    battery_domain, coulomb_domain = adjust_glider_popup_chart_domains(glider_df, battery_variable, battery_domain, coulomb_domain)

    # Create the base chart we will add more to
    # This allows added charts to share axes and/or interactivity
    base = alt.Chart(plot_df).encode(
        alt.X('datetime:T', timeUnit='yearmonthdatehoursminutes').axis(title=None).scale(domain=date_range)
    ).properties(
        width=300,
        height=300
    ).interactive()

    # Create the chart for battery level
    battery = base.mark_line().encode(
        alt.Y(f'{battery_variable}:Q').title(f'{battery_variable} ({battery_unit})').scale(domain=battery_domain),
    )
    battery_extrapolated = base.mark_line(color="red").encode(
        alt.Y(f'{battery_variable}_extrapolated:Q').title(''),
    )
    total_battery = alt.layer(battery, battery_extrapolated)

    # Create the chart for leakage
    leak = base.mark_line().encode( #, interpolate='monotone'
        alt.Y('m_digifin_leakdetect_reading:Q').title('m_digifin_leakdetect_reading').scale(zero=False)
    )

     # Create the chart for m_coulomb_amphr_total
    coulomb = base.mark_line().encode(
        alt.Y('m_coulomb_amphr_total:Q').title('m_coulomb_amphr_total (Ah)').scale(domain=coulomb_domain)
    )
    coulomb_extrapolated = base.mark_line(color="red").encode(
        alt.Y('m_coulomb_amphr_total_extrapolated:Q').title(''),
    )
    total_coulomb = alt.layer(coulomb, coulomb_extrapolated)

    # Combine the charts
    chart = (total_battery | leak | total_coulomb).properties(
        title=f"{glider_name}",
        autosize="pad",
        padding={"left": 20, "top": 5, "right": 20, "bottom": 10} # Extra padding since zooming can move things around
    ).configure_title(
        fontSize=24
    )
    return chart

def add_glider_markers(map, glider_data, interesting_sensors):
    '''Add markers for gliders on the map'''

    glider_names       = glider_data["glider_names"]
    gliders_df         = glider_data["gliders_df"]
    gliders_wpt_df     = glider_data["gliders_wpt_df"]
    gliders_latest_loc = glider_data["gliders_latest_loc"]

    for glider_name in glider_names:
        glider_df = gliders_df.loc[gliders_df["glider_name"] == glider_name]
        glider_path = glider_df[["latitude", "longitude"]].values.tolist()

        glider_latest_loc = gliders_latest_loc[["latitude", "longitude"]].loc[gliders_latest_loc["glider_name"] == glider_name].values.tolist()[0]

        glider_wpt_df = gliders_wpt_df.loc[gliders_wpt_df["glider_name"] == glider_name]
        glider_wpts = glider_wpt_df[["latitude", "longitude"]].values.tolist()

        # For some reason multiple markers can't point to the same CustomIcon, so this needs to be inside the loop
        glider_icon = folium.CustomIcon(
            "http://nodc.fmi.fi/uivelo/icons/slocum-icon.png",
            icon_size=(50, 27),
            icon_anchor=(25, 13)
        )

        glider_marker = folium.Marker(
            location=glider_latest_loc, icon=glider_icon
        )

        try:
            chart = create_glider_popup_chart(glider_name, glider_df, interesting_sensors)
        except (KeyError, ZeroDivisionError) as e: # Handle missing/inadequate data
            print(e)
            popup = folium.Popup(glider_name).add_to(glider_marker)
        else:
            popup = folium.Popup(glider_name).add_to(glider_marker)
            folium.VegaLite(chart).add_to(popup)

        glider_marker.add_to(map)

        folium.Circle(
            location=glider_latest_loc,
            radius=3000,
            color="red",
            fill_color="orange",
            fillOpacity=0.3,
            popup="3 km range"
        ).add_to(map)

        if(len(glider_path) > 0):
            folium.PolyLine(glider_path, popup=f"{glider_name}'s path", tooltip=None, color='red').add_to(map)

        if(len(glider_wpts) == 1):
            folium.PolyLine([glider_latest_loc]+glider_wpts, popup=f"{glider_name}'s current plan", tooltip=None).add_to(map)
        elif(len(glider_wpts) > 1):
            folium.PolyLine(glider_wpts, popup=f"{glider_name}'s current plan", tooltip=None).add_to(map)

    return map

def add_ship_markers(map, ships_df):
    '''Add markers for ships on the map'''

    # Create layers for ship markers
    uncategorized_ship_layer      = folium.map.FeatureGroup(name = "Uncategorized Ships", show = False)
    stationary_ships_layer        = folium.map.FeatureGroup(name = "Stationary ships", show = False) # Default off, mostly just unnecessary clutter at harbours
    region_sharing_ships_layer    = folium.map.FeatureGroup(name = "Region sharing ships") # Ships that are - or have a destination to go to - in gliders' regions
    within_range_ships_layer      = folium.map.FeatureGroup(name = "Within range ships")
    path_intersecting_ships_layer = folium.map.FeatureGroup(name = "Path intersecting ships")
    very_close_ships_layer        = folium.map.FeatureGroup(name = "Very close ships")
    vip_ship_layer                = folium.map.FeatureGroup(name = "VIP ships")

    for ship in ships_df.itertuples(index=False, name='Ship'):
        iframe = folium.IFrame(html=ship.tooltip_html, width=300, height=350)
        popup = folium.Popup(html=iframe, max_width=300)
        marker = plugins.BoatMarker([ship.latitude, ship.longitude], popup=popup, 
                           heading=ship.cog, pathCoords=ship.path, circleRadius=ship.range, 
                           color=ship.max_class_colour)
        
        if(ship.max_class_colour == "yellow"):
            marker.add_to(region_sharing_ships_layer)
        elif(ship.max_class_colour == "orange"):
            marker.add_to(path_intersecting_ships_layer)    
        elif(ship.max_class_colour == "red"):
            marker.add_to(within_range_ships_layer)
        elif(ship.max_class_colour == "grey"):
            marker.add_to(stationary_ships_layer)
        elif(ship.max_class_colour == "purple"):
            marker.add_to(very_close_ships_layer)
        elif(ship.max_class_colour == "#26f018"):
            marker.add_to(vip_ship_layer)
        else:
            marker.add_to(uncategorized_ship_layer)

    # Add the layers to the map
    uncategorized_ship_layer.add_to(map)
    stationary_ships_layer.add_to(map)
    region_sharing_ships_layer.add_to(map)
    within_range_ships_layer.add_to(map)
    path_intersecting_ships_layer.add_to(map)
    very_close_ships_layer.add_to(map)
    vip_ship_layer.add_to(map)

    # Add links to ant-path and semi-circle js for on-click effects to work
    link = folium.JavascriptLink("https://cdn.jsdelivr.net/npm/leaflet-ant-path@1.3.0/dist/leaflet-ant-path.js")
    map.get_root().html.add_child(link)

    link = folium.JavascriptLink("https://cdn.jsdelivr.net/npm/leaflet-semicircle@2.0.4/Semicircle.min.js")
    map.get_root().html.add_child(link)
    return map

def add_aranda_plan(map):
    '''Add Aranda's planned route to the map'''

    try:
        aranda_df = pd.read_csv("../Map Data/waterexchange.csv")
    except HTTPError:
        return

    # Strip object-type columns (string columns) of excess whitespace
    aranda_df_obj = aranda_df.select_dtypes(['object'])
    aranda_df[aranda_df_obj.columns] = aranda_df_obj.apply(lambda x: x.str.strip())
    # Drop duplicate rows (excluding decimal degree coordinates since floating point errors in conversions)
    aranda_df = aranda_df[~aranda_df.drop(["latitude", "longitude"], axis=1).duplicated()]
    # aranda_df = aranda_df[~aranda_df["Index"].duplicated()]

    aranda_df["Datetime"] = aranda_df.apply(lambda row: datetime(int(row["Date"][-4:]), int(row["Date"][3:5]), int(row["Date"][0:2]), int(row["Time"]), int(100*(row["Time"]-int(row["Time"])))), axis=1)
    aranda_df["Deg_coords"] = aranda_df["Lat"] + "N " + aranda_df["Long"] + "E"
    
    aranda_stations_layer = folium.map.FeatureGroup(name = "Aranda stations", show = False)
    
    # List all indexes per station (we need to use coordinates since the same name can have multiple coordinates, e.g. HELSINKI)
    stations_df = aranda_df[~aranda_df["Deg_coords"].duplicated()]
    station_indexes = aranda_df.groupby('Deg_coords')['Index'].apply(lambda x: 
                                                                  ', '.join(str(index) for index in list(x))).copy()
    station_indexes.name = "Index_html_string"
    stations_df = stations_df.merge(station_indexes, left_on="Deg_coords", right_index=True, how="left")

    # List all datetimes per station
    station_datetimes = aranda_df.groupby('Deg_coords')['Datetime'].apply(lambda x: 
                                                                  '<br>'.join(str(index) for index in list(x))).copy()
    station_datetimes.name = "Datetime_html_string"
    stations_df = stations_df.merge(station_datetimes, left_on="Deg_coords", right_index=True, how="left")


    stations_df['tooltip_html'] = stations_df.apply(lambda station: '</span></p><p style="text-align:left;">'.join(
                ['<p style="text-align:left;"> ' + 
                'Station: <span style="float:right;">'    + str(station['Station']),
                'Station Nr: <span style="float:right;">' + station['Index_html_string'],
                'When: <span style="float:right;">'       + station['Datetime_html_string'] + 
                '</span></p>']), axis=1)

    for station in stations_df.itertuples(index=False, name='Ship'):
        iframe = folium.IFrame(html=station.tooltip_html, width=220, height=120)
        popup = folium.Popup(html=iframe, max_width=220)
        folium.CircleMarker([station.latitude, station.longitude], popup=popup, color="green").add_to(aranda_stations_layer)

    folium.PolyLine(aranda_df[["latitude", "longitude"]].values.tolist(), popup="Aranda's current plan", color="green", opacity=0.3).add_to(aranda_stations_layer)
    aranda_stations_layer.add_to(map)

    return map

def add_markers(map, ships_df, glider_data, interesting_sensors):
    '''Add various markers on the map'''

    map = add_glider_markers(map, glider_data, interesting_sensors)
    map = add_ship_markers(map, ships_df)
    map = add_aranda_plan(map)

    return map

def add_tile_layers(map):
    '''Add tile layers to the map'''

    # Default base map
    # Normally "tiles" and "name" parameters would be enough, but since we want custom attribution...
    folium.TileLayer(tiles='https://tile.openstreetmap.org/{z}/{x}/{y}.png', #tiles='openstreetmap',
                     name='OpenStreetMap',
                     max_zoom = 19,
                     overlay=False,
                     attr='Data by: Fintraffic / digitraffic.fi, license CC 4.0 BY, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors').add_to(map)

    # Alternate base map from bathymetry data
    bathymetry_layer = folium.map.FeatureGroup(name = "EMODNET Bathymetry and coast lines", overlay = False, show=False)

    folium.WmsTileLayer(url = "https://ows.emodnet-bathymetry.eu/wms", 
                        layers="mean_atlas_land", 
                        fmt="image/png",
                        attr='Data by: Fintraffic / digitraffic.fi, license CC 4.0 BY, EMODnet-Bathymetry', 
                        name="EMODNET Bathymetry", 
                        overlay=False).add_to(bathymetry_layer)
    
    folium.WmsTileLayer(url = "https://ows.emodnet-bathymetry.eu/wms", 
                        layers="coastlines", 
                        fmt="image/png",
                        attr='Data by: Fintraffic / digitraffic.fi, license CC 4.0 BY, EMODnet-Bathymetry', 
                        name="EMODNET coast lines", 
                        transparent = True).add_to(bathymetry_layer)
    
    bathymetry_layer.add_to(map)
    
    # Overlay for sea marks
    folium.TileLayer(tiles = "http://t1.openseamap.org/seamark/{z}/{x}/{y}.png", 
                     name = "OpenSeaMap", 
                     min_zoom = 8, 
                     max_zoom = 14,
                     overlay = True,
                     attr = '&copy; <a href="http://www.openseamap.org">OpenSeaMap</a> contributors').add_to(map)
    
    # Overlay for fishing ship traffic density, default off
    folium.WmsTileLayer(url = "https://ows.emodnet-humanactivities.eu/geoserver/emodnet/ows?service=WMS", 
                        layers="emodnet:vesseldensity_01avg", 
                        fmt="image/png",
                        transparent = True,
                        attr='EMODNET-Human Activities and CLS', 
                        maxZoom = 20,
                        minZoom = 3,
                        show=False,
                        name="EMODNET Fishing vessel traffic density").add_to(map)
    
    # Overlay for passenger ship traffic density, default off
    folium.WmsTileLayer(url = "https://ows.emodnet-humanactivities.eu/geoserver/emodnet/ows?service=WMS", 
                        layers="emodnet:vesseldensity_08avg", 
                        fmt="image/png",
                        transparent = True,
                        attr='EMODNET-Human Activities and CLS', 
                        maxZoom = 20,
                        minZoom = 3,
                        show=False,
                        name="EMODNET Passenger vessel traffic density").add_to(map)
    
    # Overlay for cargo ship traffic density, default off
    folium.WmsTileLayer(url = "https://ows.emodnet-humanactivities.eu/geoserver/emodnet/ows?service=WMS", 
                        layers="emodnet:vesseldensity_09avg", 
                        fmt="image/png",
                        transparent = True,
                        attr='EMODNET-Human Activities and CLS', 
                        maxZoom = 20,
                        minZoom = 3,
                        show=False,
                        name="EMODNET Cargo vessel traffic density").add_to(map)

    # Overlay for EEZ boundaries
    folium.WmsTileLayer(url = "http://geo.vliz.be/geoserver/MarineRegions/wms?", 
                        layers = "eez_boundaries",
                        fmt="image/png", 
                        transparent=True, 
                        attr='Marineregions.org', 
                        name="EEZ",
                        opacity=0.10).add_to(map)

    # Overlay for Finnish navigation charts (default to off due to low transparency)
    folium.WmsTileLayer(url = "https://julkinen.traficom.fi/s57/wms", 
                        layers = "cells",
                        attr="--- Navigation Chart service based on Liikennevirasto's raster data. Permit CC 4.0" +
                             " Source: Liikennevirasto. Not for navigation. Does not fill quality of official navigation charts.", 
                        name = "Navigation chart",
                        transparent=True,
                        show=False,
                        fmt="image/png",
                        min_zoom = 7).add_to(map)
    
    return map

def add_deployment_info(map):
    '''Add an info text box showing glider deployment times'''
    deployment_positions = read_json('../Map Data/Gliders/JSONs/deployment_positions.json')
    glider_names = list(deployment_positions.keys())

    deployment_html = """
            <p style="padding: 0px; margin: 0px;text-align:left;">"""
    for glider_name in glider_names:
        deployment_html += f"""
                {str.capitalize(glider_name)} deployed: &nbsp 
                    <span style="float:right;"> {deployment_positions[glider_name]["datetime"]} </span><br>"""

    deployment_html = deployment_html.rstrip(deployment_html[-4]) # Remove last (extra) linebreak
    deployment_html += """
            </p>"""

    # Injecting custom css through branca macro elements and template, give it a name
    textbox_css = f"""
    {{% macro html(this, kwargs) %}}

        <div id="textbox" class="textbox">
        <div class="textbox-title">FMI glider missions</div>
        <div class="textbox-content">
            {deployment_html}
        </div>
        </div>


    <style type='text/css'>
    .textbox {{
        position: absolute;
        z-index:9999;
        border-radius:4px;
        background: rgba( 255, 255, 255, 0.7 );
        //background: rgba( 28, 25, 56, 0.25 );
        //box-shadow: 0 8px 32px 0 rgba( 31, 38, 135, 0.37 );
        //backdrop-filter: blur( 4px );
        //-webkit-backdrop-filter: blur( 4px );
        //border: 4px solid rgba( 215, 164, 93, 0.2 );
        padding: 10px;
        font-size:14px;
        right: 20px;
        //bottom: 20px;
        top: 20px;
        color: blue;
    }}
    .textbox .textbox-title {{
        color: darkblue;
        text-align: center;
        margin-bottom: 5px;
        font-weight: bold;
        font-size: 22px;
        }}
    </style>
    {{% endmacro %}}
    """
    # configuring the custom style (you can call it whatever you want)
    my_custom_style = MacroElement()
    my_custom_style._template = Template(textbox_css)

    # Adding my_custom_style to the map
    map.get_root().add_child(my_custom_style)

    return map

def add_map_tools(map):
    '''Add interactive tools to the map'''

    # Cursor coordinates, shown bottom right
    plugins.MousePosition().add_to(map)

    # Measure tool, bottom left
    plugins.MeasureControl(primary_length_unit   = 'kilometers', 
                           secondary_length_unit = 'miles', 
                           primary_area_unit     = 'hectares', 
                           secondary_area_unit   = 'acres',
                           completed_color       = 'red',
                           active_color          = 'orange',
                           position              = 'bottomright').add_to(map)

    # Various drawing tools, top left
    plugins.Draw(draw_options={"polyline": {"shapeOptions": {"color": "red"}}}).add_to(map)

    # Fullscreen toggle, top left
    plugins.Fullscreen().add_to(map)

    # Controlling layers
    folium.LayerControl(position='bottomleft').add_to(map)

    return map

def draw_map(map_center, ships_df, vip_ships, db_connection):
    '''Draw interactive map based on AIS data'''
    map = folium.Map(location=map_center, zoom_start=9, tiles=None)
    map = add_on_click_functionality(map)

    glider_data, interesting_sensors = load_glider_data()

    if(glider_data == None):
        # Still draw a map of ships if there's no active gliders
        ships_df = process_no_gliders_ship_data(ships_df)
        map = add_no_gliders_ship_markers(map, ships_df, vip_ships)
        map = add_aranda_plan(map)
    else:
        # Re-center map on latest glider location update
        gliders_df = glider_data["gliders_df"]
        latest_glider_latitude = gliders_df.loc[gliders_df["datetime"].idxmax()]["latitude"]
        latest_glider_longitude = gliders_df.loc[gliders_df["datetime"].idxmax()]["longitude"]
        map.location = [latest_glider_latitude, latest_glider_longitude]
        
        ships_df = process_ship_data(ships_df, glider_data, vip_ships, db_connection)   
        map = add_markers(map, ships_df, glider_data, interesting_sensors)     

    map = add_tile_layers(map)
    map = add_map_tools(map)
    map = add_deployment_info(map)

    return map