#############################
#         Imports           #
#############################

import requests
import pandas as pd
import numpy as np
import sqlite3
from math import floor
from sqlite3 import Error
from datetime import datetime, timedelta

import geopandas as gpd
from shapely.geometry import Polygon, Point

# NOTE: Required downloads: 
# UpdatedPub150.csv from https://msi.nga.mil/Publications/WPI 
# code-list_csv.csv from https://datahub.io/core/un-locode

#############################
#         API Calls         #
#############################

# To track errors/loads by Digitraffic as requested in their guidelines
# Don’t send any PII (personally identifiable information) via the headers!
# For more info see: https://www.digitraffic.fi/en/support/instructions/#general-considerations

HEADERS = {'Digitraffic-User': 'Foo/Bar'} 

# /locations: 'Find latest vessel locations by mmsi and optional 
#              timestamp interval in milliseconds from Unix epoch.'
#   mmsi
#   from
#   to
#   radius
#   latitude
#   longitude
# /vessels: 'Return latest vessel metadata for all known vessels.'
#   from
#   to
# /vessels/mmsi: 'Return latest vessel metadata by mmsi.'


# NOTE: Python timestamps in seconds, digitraffic in milliseconds

def get_ships_meta(since):
    '''Get the metadata of all ships since given timestamp'''
    # https://meri.digitraffic.fi/api/ais/v1/vessels
    
    host = "https://meri.digitraffic.fi/api/ais/v1/"
    tag = "vessels"
    shipmeta_url = f'{host}{tag}?from={since}'
    meta_response = requests.get(shipmeta_url, headers=HEADERS)
    return meta_response.json()

def get_ship_meta(MMSI):
    '''Get the metadata of a ship with MMSI'''
    # https://meri.digitraffic.fi/api/ais/v1/vessels/338926878

    host = "https://meri.digitraffic.fi/api/ais/v1/"
    tag = "vessels/"
    shipmeta_url = f'{host}{tag}{MMSI}'
    meta_response = requests.get(shipmeta_url, headers=HEADERS)
    return meta_response.json()
    
def get_ships_locations(latitude, longitude, distance, since):
    '''Get the location of ships close to lat/lon'''
    # https://meri.digitraffic.fi/api/ais/v1/locations?from=1692184014&radius=20&latitude=59.837&longitude=23.29
    
    host = "https://meri.digitraffic.fi/api/ais/v1/"
    tag = "locations"
    shiplocat_url = f'{host}{tag}?from={since}&radius={distance}&latitude={latitude}&longitude={longitude}'
    locat_response = requests.get(shiplocat_url, headers=HEADERS)
    return locat_response.json()

def get_ship_location(mmsi):
    '''Get the location of a ship with MMSI'''
    # https://meri.digitraffic.fi/api/ais/v1/locations?mmsi=338926878
    
    host = "https://meri.digitraffic.fi/api/ais/v1/"
    tag = "locations"
    shiplocat_url = f'{host}{tag}?mmsi={mmsi}'
    locat_response = requests.get(shiplocat_url, headers=HEADERS)
    return locat_response.json()

#############################
#      Data processing      #
#############################

 ###########################
#    Destination analysis   #
 ###########################

 # TODO: Extensive style edits

def format_port_identifiers(locodes):
    '''Format port names and locodes for regex purposes'''
    # Edit names to help matching
    locodes["SimpleName"] = locodes["NameWoDiacritics"].str.upper()
    locodes.replace({"SimpleName": {r"[^A-Z/(\s]": ""}}, regex = True, inplace = True)
    locodes.SimpleName.replace(r"\s+", " ", inplace = True, regex = True)
    locodes.SimpleName.str.strip()

    # Turn names/locodes into regex patterns
    locodes["LocodePattern"] = locodes["Country"] + r"\s*" + locodes["Location"]
    locodes["NamePattern"] = locodes["SimpleName"]
    locodes.replace({"NamePattern": {r"\s*\(": "|"}}, regex = True, inplace = True)
    locodes.replace({"NamePattern": {r"/": "|"}}, regex = True, inplace = True)

    # Add exceptions for common alternatives
    locodes.replace({"NamePattern": {"SAINT PETERSBURG": "PETERSBURG|PETERBURG|SPB"}}, inplace = True)
    locodes.replace({"NamePattern": {"USTLUGA": "UST[^A-Z]*LUGA"}}, inplace = True) # "UST'-LUGA"
    locodes.replace({"NamePattern": {"TALLINN": "TALLINN|TALLIN"}}, inplace = True)
    locodes.replace({"NamePattern": {"ANTWERPEN": "ANTWERPEN|ANTWERP"}}, inplace = True)
    locodes.replace({"NamePattern": {"TURKU": "TURKU|PANSIO"}}, regex = True, inplace = True)
    # TODO:
    # NAUVO    NAUVO|PROSTVIK|PARNAS    Nagu (Nauvo)
    # PARAINEN LILLMALO|PARAINEN        Parainen (Pargas)
    # HELSINKI HKI|HEL|HELSINKI         Helsingfors (Helsinki)
    # KORPO    KORPO|RETAIS             Korpo (Korppoo)
    # VYSOTSK  VISOTSK|VYSOTSK
    # e.g. savonlinna -> saimaa|savonlinna
    # retais-pärnäs Nauvo-Korppoo 

    # Edit names to help matching
    locodes.replace({"SimpleName": {r"\(.*": ""}}, regex = True, inplace = True)
    locodes.replace({"SimpleName": {r"/.*": ""}}, regex = True, inplace = True)
    locodes["SimpleName"] = locodes.SimpleName.str.strip()

    # Remove SimpleName value from duplicates outside Europe
    # and all but one european
    dupes = locodes[locodes.duplicated(subset = ["SimpleName"], keep = False)].copy()
    eu_dupes = dupes[(dupes['Latitude'] > 25) & (dupes['Latitude'] < 75) & 
                     (dupes['Longitude'] > -25) & (dupes['Longitude'] < 45)]
    eu_dupes = eu_dupes.drop_duplicates(subset = ['SimpleName'])
    dupes["SimpleName"] = ""
    dupes.update(eu_dupes["SimpleName"])
    locodes.update(dupes["SimpleName"], overwrite=True)
    locodes.SimpleName.replace(r"^\s*$", pd.NA, regex = True, inplace = True)

    return locodes

def convert_coordinates_ddmm_to_dddd(coord):
    '''Convert coordinates from degrees+minutes to degrees+decimals'''
    
    degs = coord//100
    mins = coord % 100

    return round(degs + mins/60, 5)

def extract_coordinates(locodes):
    '''Split coordinates to floats from string'''
    locodes["Latitude"]  = locodes["Coordinates"].str.extract(r"(\d*)[NS]")
    locodes["Longitude"] = locodes["Coordinates"].str.extract(r"(\d*)[WE]")

    locodes["Latitude"]  = convert_coordinates_ddmm_to_dddd(pd.to_numeric(locodes["Latitude"]))
    locodes["Longitude"] = convert_coordinates_ddmm_to_dddd(pd.to_numeric(locodes["Longitude"]))

    locodes.loc[locodes["Coordinates"].str.contains('S', na = False), "Latitude"] *= -1
    locodes.loc[locodes["Coordinates"].str.contains('W', na = False), "Longitude"] *= -1 

    return locodes

def manual_coordinate_updates(locodes):
    '''Add missing coordinates'''
    # TODO: Check all baltic ports with missing coordinates
    # TODO: Manually add missing data
    locodes.loc[(locodes["Country"] == "RU") & (locodes["Location"] == "IAR"), "Coordinates"] = "5760N 03991E" # Yaroslavl
    locodes.loc[(locodes["Country"] == "RU") & (locodes["Location"] == "LOM"), "Coordinates"] = "5993N 03033E" # Lomonosov
    locodes.loc[(locodes["Country"] == "SE") & (locodes["Location"] == "ROR"), "Coordinates"] = "5993N 02438E" # Rönnskär
    locodes.loc[(locodes["Country"] == "RU") & (locodes["Location"] == "ONG"), "Coordinates"] = "6391N 03809E" # Onega
    locodes.loc[(locodes["Country"] == "FI") & (locodes["Location"] == "PUU"), "Coordinates"] = "6152N 02817E" # Puumala
    locodes.loc[(locodes["Country"] == "FI") & (locodes["Location"] == "HAU"), "Coordinates"] = "6518N 02532E" # Haukipudas
    locodes.loc[(locodes["Country"] == "SE") & (locodes["Location"] == "HLD"), "Coordinates"] = "6368N 02034E" # Holmsund
    locodes.loc[(locodes["Country"] == "FI") & (locodes["Location"] == "VKO"), "Coordinates"] = "6041N 02626E" # Valkom
    locodes.loc[(locodes["Country"] == "SE") & (locodes["Location"] == "BAT"), "Coordinates"] = "6579N 02342E" # Båtskärsnäs
    locodes.loc[(locodes["Country"] == "SE") & (locodes["Location"] == "OGR"), "Coordinates"] = "6047N 01843E" # Öregrund
    locodes.loc[(locodes["Country"] == "GI") & (locodes["Location"] == "GIB"), "Coordinates"] = "3609N 00520W" # Gibraltar
    locodes.loc[(locodes["Country"] == "IN") & (locodes["Location"] == "KRI"), "Coordinates"] = "1424N 08013W" # Krishnapatnam
    locodes.loc[(locodes["Country"] == "FI") & (locodes["Location"] == "LAN"), "Coordinates"] = "6007N 02018W" # Långnäs
    locodes.loc[(locodes["Country"] == "IT") & (locodes["Location"] == "RAN"), "Coordinates"] = "4447N 01226W" # Ravenna

    return locodes

def manual_port_additions(locodes):
    '''Add completely new rows for frequently used missing locations'''
    # TODO: 
    new_row = {'Country':'SE', 'Location':'SAH', 'Coordinates':'5609N 01585E', 
               'Name':'Sandhamn', 'NameWoDiacritics':'Sandhamn'}
    locodes = pd.concat([locodes, pd.DataFrame([new_row])], ignore_index=True)
    new_row = {'Country':'SE', 'Location':'NRR', 'Coordinates':'5893N 01797E', 
               'Name':'Norvik', 'NameWoDiacritics':'Norvik'}
    locodes = pd.concat([locodes, pd.DataFrame([new_row])], ignore_index=True)
    new_row = {'Country':'EE', 'Location':'KUN', 'Coordinates':'5951N 02656E', 
               'Name':'Kunda', 'NameWoDiacritics':'Kunda'}
    locodes = pd.concat([locodes, pd.DataFrame([new_row])], ignore_index=True)
    new_row = {'Country':'SE', 'Location':'GR2', 'Coordinates':'6034N 01846E', 
               'Name':'Gräsö', 'NameWoDiacritics':'Graso'}
    locodes = pd.concat([locodes, pd.DataFrame([new_row])], ignore_index=True)
    new_row = {'Country':'EE', 'Location':'MUU', 'Coordinates':'5950N 02495E', 
               'Name':'Muuga', 'NameWoDiacritics':pd.NA} # Some use this instead of EEMUG
    locodes = pd.concat([locodes, pd.DataFrame([new_row])], ignore_index=True)
    # 2012: The code FIOLU also exist in UN/LOCODE but should not be used
    # new_row = {'Country':'FI', 'Location':'OLU', 'Coordinates':'5951N 02656E', 
    #            'Name':'Oulu', 'NameWoDiacritics':'Oulu'}
    # locodes = pd.concat([locodes, pd.DataFrame([new_row])], ignore_index=True)
    # Consider adding Utö, but take note SEUTO is separate and exists
    # FIUTO doesn't exist, we could just make it as a placeholder
    # STIRSUDDEN used a lot, consider making it up (eg XX STR)

    return locodes

def world_port_index_coordinate_updates(locodes):
    ''' Load from WPI to fill in (some) missing coordinates 
        (https://msi.nga.mil/Publications/WPI World Port Index)'''
    
    WPI_locodes    = pd.read_csv("../Map Data/Ports/UpdatedPub150.csv", 
                                 usecols=["UN/LOCODE", "Main Port Name", 
                                          "Latitude", "Longitude"]) 
    missing_coordinates = locodes[locodes['Coordinates'].isna()].copy()
    missing_coordinates["UN/LOCODE"] = missing_coordinates["Country"] + " " + missing_coordinates["Location"]
    missing_coordinates = missing_coordinates[["Country", "Location", "UN/LOCODE"]]

    # Merging will reset index, turn it into a column to save it
    missing_coordinates.reset_index(inplace = True)

    missing_coordinates = missing_coordinates.merge(WPI_locodes, on = "UN/LOCODE")

    # Use the old index again
    missing_coordinates.set_index('index', inplace = True)
    missing_coordinates.index.name = None

    # Some WPI locodes have multiple rows, drop these duplicates
    missing_coordinates = missing_coordinates.drop_duplicates(subset = ["UN/LOCODE"])

    # Split coordinates to floats from string
    locodes = extract_coordinates(locodes)

    # Fill in missing coordinates from WPI (using index matching)
    locodes.update(missing_coordinates[["Latitude", "Longitude"]])
   
    return locodes

def add_missing_port_data(locodes):
    '''Add missing port data'''
    # TODO: Check https://ec.europa.eu/eurostat/cache/metadata/Annexes/mar_esms_an2.xlsx 
    #       for better data, has some of the missing rows at least?

    # Add missing coordinates
    locodes = manual_coordinate_updates(locodes)

    # Add completely new rows for frequently used missing locations
    locodes = manual_port_additions(locodes)

    # Load from WPI to fill in (some) missing coordinates 
    # (https://msi.nga.mil/Publications/WPI World Port Index)
    locodes = world_port_index_coordinate_updates(locodes)

    # Drop any rows with still missing coordinates
    locodes.dropna(subset=["Latitude",  "Longitude"], inplace = True, ignore_index = True)

    return locodes

def load_port_data():
    '''Load UN locode data'''
    
    na_values = ["", 
             "#N/A", 
             "#N/A N/A", 
             "#NA", 
             "-1.#IND", 
             "-1.#QNAN", 
             "-NaN", 
             "-nan", 
             "1.#IND", 
             "1.#QNAN", 
             "<NA>", 
             "N/A", 
             #"NA", # Needed to prevent Namibia (NA) from being interpreted as missing value
             "NULL", 
             "NaN", 
             "n/a", 
             "nan", 
             "null"]
    
    # Load The United Nations Code for Trade and Transport Locations 
    locodes = pd.read_csv("../Map Data/Ports/code-list_csv.csv", 
                          usecols=["Country", "Location", "Name", "NameWoDiacritics", 
                                   "Coordinates", "Function"], 
                                   keep_default_na = False, na_values = na_values) 
    # NOTE: Currently https://datahub.io/core/un-locode (outdated)
    # but https://unece.org/trade/cefact/UNLOCODE-Download is the true source
    # 2023 version however split and offers no noticeable improvements

    # Limit to ports, canals and inland ports
    # 0 = Function not known, to be specified # Just in case
    # 1 = Port
    # 6 = Multimodal Functions (ICDs, etc.)   # No idea what that means, but includes 
                                              # canals like DECKL - Kiel canal
    # 8 = Inland ports                        # Just in case

    # TODO: Consider adding some inland locations if they're used enough
    # Edit frequently used location's classifications

    # EEPLA also has 2 separate codes for ports, so we simplify here
    locodes.loc[(locodes["Country"] == "EE") & 
                (locodes["Location"] == "PLA"), "Function"] = "123----B"
    # FIRAH incorrectly only marked as 3
    locodes.loc[(locodes["Country"] == "FI") & 
                (locodes["Location"] == "RAH"), "Function"] = "1-3-----"

    locodes = locodes.loc[locodes["Function"].str.contains("[0168]", na = False)]

    # Drop port identifier column
    locodes = locodes.drop(columns=['Function'])

    # Remove troublesome names from name matching
    # E.g. "Search & Rescue" vs. USRES
    locodes.loc[locodes["NameWoDiacritics"] == "Russia", "NameWoDiacritics"]  = pd.NA
    # locodes.loc[locodes["NameWoDiacritics"] == "Denmark", "NameWoDiacritics"] = pd.NA # No practical difference
    locodes.loc[locodes["NameWoDiacritics"] == "Rescue", "NameWoDiacritics"]  = pd.NA 
    locodes.loc[locodes["NameWoDiacritics"] == "Harbor", "NameWoDiacritics"]  = pd.NA
    locodes.loc[locodes["NameWoDiacritics"] == "Hel",    "NameWoDiacritics"]  = pd.NA
    locodes.loc[locodes["NameWoDiacritics"] == "Baltic", "NameWoDiacritics"]  = pd.NA

    # Add missing data
    locodes = add_missing_port_data(locodes)
    
    # Format port names and locodes for regex purposes
    locodes = format_port_identifiers(locodes)
 
    return locodes

def match_locodes(meta_df, locodes):
    '''Use regex to get valid locodes from destination column'''
    # Replace destination underscores with spaces for easier matching at word boundaries
    meta_df.replace({"destination": {"_": " "}}, regex = True, inplace = True)

    # Take only non-NA locodes, use with regex on metadata
    valid_patterns = locodes.dropna(subset=["LocodePattern"])["LocodePattern"]

    locode_pattern = "|".join(valid_patterns)
    extracted_locodes = meta_df.destination.str.extractall(r"\b(" + locode_pattern + r")\b")

    # Turn multi-index into columns
    locode_matches = extracted_locodes.reset_index(level = ["match"]).pivot(columns = "match")
    locode_matches.columns = locode_matches.columns.droplevel()

    locode_matches.rename(columns = {0: "destinationOne", 
                                     1: "destinationTwo", 
                                     2: "destinationThree"}, inplace = True)
    locode_matches.columns.name = None

    # Ensure number of columns is 3 for consistency
    temp = pd.DataFrame(index = locode_matches.index, columns = ['destinationOne', 
                                                                 'destinationTwo', 
                                                                 'destinationThree'], 
                                                                 dtype = "string")
    temp.update(locode_matches.iloc[:, 0:3])
    locode_matches = temp

    # Remove excess whitespace for easier matching
    locode_matches.replace(r"\s+", " ", inplace = True, regex = True)
    locode_matches.destinationOne.str.strip()
    locode_matches.destinationTwo.str.strip()
    locode_matches.destinationThree.str.strip()

    # Merge to metadata
    meta_df = meta_df.merge(locode_matches, how = 'left', 
                            left_index = True, right_index = True)

    return meta_df

def replace_invalid_alt_port_names(loc_name_matches, invalid_alt_names, column_name):
    '''Replace alternate port names with the ones we use to find locodes'''
    # Merging will reset index, turn it into a column to save it
    loc_name_matches.reset_index(inplace = True)

    loc_name_matches = loc_name_matches.merge(invalid_alt_names[["Name2", "Name1"]], 
                                              how='left', 
                                              left_on=column_name, right_on="Name2")
    # Use the old index again
    loc_name_matches.set_index('index', inplace = True)
    loc_name_matches.index.name = None

    # Replace names not used in locodes
    loc_name_matches[column_name].mask(loc_name_matches['Name2'].notna(), 
                                       loc_name_matches['Name1'], inplace = True)

    loc_name_matches.drop(columns = ["Name2", "Name1"], inplace = True)

    return loc_name_matches

def match_port_names(meta_df, locodes):
    '''Use regex to get valid port names from destination column'''
    # Get all destinations that weren't valid locodes
    destination_names = meta_df[meta_df["destinationOne"].isna()].destination

    # Get all non-empty name patterns
    valid_patterns = locodes.dropna(subset=["NamePattern"])["NamePattern"]

    # Use patterns with regex on destinations
    loc_name_pattern = "|".join(valid_patterns)
    extracted_loc_names = destination_names.str.extractall(r"\b(" + loc_name_pattern + r")\b")

    # Turn multi-index into columns
    loc_name_matches = extracted_loc_names.reset_index(level = ["match"]).pivot(columns = "match")
    loc_name_matches.columns = loc_name_matches.columns.droplevel()

    loc_name_matches.rename(columns = {0: "SimpleNameOne", 
                                       1: "SimpleNameTwo", 
                                       2: "SimpleNameThree"}, inplace = True)
    loc_name_matches.columns.name = None

    # Ensure number of columns is 3 for consistency
    temp = pd.DataFrame(index = loc_name_matches.index, columns = ['SimpleNameOne', 
                                                                   'SimpleNameTwo', 
                                                                   'SimpleNameThree'], 
                                                                   dtype = "string")
    temp.update(loc_name_matches.iloc[:, 0:3])
    loc_name_matches = temp

    # Manually replace certain names not used in locodes
    loc_name_matches.replace(".*(PETERSBURG|PETERBURG|SPB)", "SAINT PETERSBURG", 
                             inplace = True, regex = True) # TODO: Consider LED
    loc_name_matches.replace("ANTWERP", "ANTWERPEN", inplace = True, regex = True)
    loc_name_matches.replace("PANSIO", "TURKU", inplace = True, regex = True)
    # TODO: Consider HEL, HKI

    # Manipulate columns for easier merging
    loc_name_matches.replace(r"[^A-Z\s]", "", inplace = True, regex = True)
    loc_name_matches.replace(r"\s+", " ", inplace = True, regex = True)
    loc_name_matches.SimpleNameOne.str.strip()
    loc_name_matches.SimpleNameTwo.str.strip()
    loc_name_matches.SimpleNameThree.str.strip()

    # Create a dataframe from the placenames with alternatives
    multi_patterns = pd.DataFrame(valid_patterns.loc[valid_patterns.str.contains(r"\|", na = False)])

    multi_patterns["Name1"] = multi_patterns.NamePattern.str.extract(r"(.*)\|")
    multi_patterns["Name2"] = multi_patterns.NamePattern.str.extract(r"\|(.*)")

    # Choose the ones that aren't used in locodes-dataframe so we can replace them
    invalid_alt_names = multi_patterns[~multi_patterns['Name2'].isin(locodes)].copy()

    # Edit for easier merging
    invalid_alt_names.replace(r"[^A-Z\s]", "", inplace = True, regex = True)
    invalid_alt_names.replace(r"\s+", " ", inplace = True, regex = True)
    invalid_alt_names.Name1.str.strip()
    invalid_alt_names.Name2.str.strip()
    invalid_alt_names = invalid_alt_names.drop(columns=["NamePattern"])
    # If one alt name maps to multiple, just pick first - should be good enough
    invalid_alt_names.drop_duplicates(subset = ["Name2"], inplace = True) 

    loc_name_matches.dropna(subset = ["SimpleNameOne"], inplace = True)

    loc_name_matches = replace_invalid_alt_port_names(loc_name_matches, 
                                                      invalid_alt_names, "SimpleNameOne")
    loc_name_matches = replace_invalid_alt_port_names(loc_name_matches, 
                                                      invalid_alt_names, "SimpleNameTwo")
    loc_name_matches = replace_invalid_alt_port_names(loc_name_matches, 
                                                      invalid_alt_names, "SimpleNameThree")

    return loc_name_matches

def extract_locode_from_name(extracted_loc_names, locodes, name_column, destination_column):
    '''Use port names to retrieve corresponding locodes'''  
    # Make a copy so we can drop NAs for merging
    # Merging will reset index, turn it into a column to save it
    names_to_locodes = extracted_loc_names.copy().reset_index()[[name_column, 'index']]
    names_to_locodes.dropna(inplace = True)

    names_to_locodes = names_to_locodes.merge(locodes[["SimpleName", "Country", "Location"]], 
                                              how='left', 
                                              left_on=name_column, right_on="SimpleName")

    # Use the old index again
    names_to_locodes.set_index('index', inplace = True)
    names_to_locodes.index.name = None

    names_to_locodes[destination_column] = names_to_locodes["Country"] + names_to_locodes["Location"]
    names_to_locodes = names_to_locodes[destination_column]

    # Set destinationOne column and merge
    extracted_loc_names[destination_column] = pd.NA

    extracted_loc_names.update(names_to_locodes)

    return extracted_loc_names

def match_port_identifiers(meta_df, locodes):
    '''Match metadata destinations with port locodes'''    
    meta_df = match_locodes(meta_df, locodes)

    extracted_loc_names = match_port_names(meta_df, locodes)

    # Merge to get locodes
    locodes.SimpleName.replace(r"[^A-Z\s]", "", inplace = True, regex = True)
    locodes.SimpleName.replace(r"\s+", " ", inplace = True, regex = True)
    locodes.SimpleName.str.strip()
    
    extracted_loc_names = extract_locode_from_name(extracted_loc_names, locodes, 
                                                   "SimpleNameOne",   "destinationOne")
    extracted_loc_names = extract_locode_from_name(extracted_loc_names, locodes, 
                                                   "SimpleNameTwo",   "destinationTwo")
    extracted_loc_names = extract_locode_from_name(extracted_loc_names, locodes, 
                                                   "SimpleNameThree", "destinationThree")

    meta_df.update(extracted_loc_names[["destinationOne", 
                                        "destinationTwo", 
                                        "destinationThree"]], overwrite=False)

    # For consistency, replace NaNs etc. with NAs
    meta_df.fillna(pd.NA, inplace = True)

    # Remove all whitespace from destination locodes for easier matching
    meta_df.destinationOne = meta_df.destinationOne.str.replace(r"\s+", "", regex = True)
    meta_df.destinationTwo = meta_df.destinationTwo.str.replace(r"\s+", "", regex = True)
    meta_df.destinationThree = meta_df.destinationThree.str.replace(r"\s+", "", regex = True)

    return meta_df

def classify_regions(dataframe, latitude_column, longitude_column, region_column):
    '''Classify locations based on coordinates''' 
    # NOTE: GeoPandas uses LonLat
    bothnian_bay    = Polygon([[22,  66],  [25.6,65.9],[26,  65],  [22.5,63.1],[19.7,63.6]])
    bothnian_sea    = Polygon([[16.6,63],  [16.6,60.5],[18,  60.5],[21.5,60.7],[22.5,63.1],[19.7,63.6]])
    archipelago_sea = Polygon([[18,  60.5],[21.5,60.7],[23,  60.5],[23,  60],  [21.8,59.4],[18.6,59.7]])
    gulf_of_finland = Polygon([[23,  60],  [21.8,59.4],[23.5,58.8],[30.8,59.5],[29.5,61]])
    saimaa_laatokka = Polygon([[30.8,59.5],[29.5,61],  [26,  61],  [26,  63.5],[31,  63.5],[34,  60]])

    locations_gdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy(dataframe[longitude_column], 
                                                                 dataframe[latitude_column]), 
                                                                 crs="EPSG:4979")

    dataframe[region_column] = "Baltic Sea"

    dataframe.loc[locations_gdf.intersects(bothnian_bay),    region_column] = "Bothnian Bay"
    dataframe.loc[locations_gdf.intersects(bothnian_sea),    region_column] = "Bothnian Sea"
    dataframe.loc[locations_gdf.intersects(archipelago_sea), region_column] = "Archipelago Sea"
    dataframe.loc[locations_gdf.intersects(gulf_of_finland), region_column] = "Gulf of Finland"
    dataframe.loc[locations_gdf.intersects(saimaa_laatokka), region_column] = "Saimaa and Laatokka"
    
    return dataframe

def classify_destination_column(meta_df, regions, destination_column, region_column):
    '''Classify a column of destination locations relative to archipelago'''
    meta_df = meta_df.merge(regions, how='left', left_on=destination_column, right_on="Locode")
    meta_df.rename(columns = {"PortLocation": region_column}, inplace = True)
    meta_df.drop(columns=["Locode"], inplace = True)

    return meta_df

def classify_destination_regions(meta_df, regions):
    '''Classify destination locations relative to archipelago''' 
    regions["Locode"] = regions["Country"] + regions["Location"]
    regions.drop(columns=["Country", "Location"], inplace = True)
    regions.drop_duplicates(inplace = True)

    meta_df = classify_destination_column(meta_df, regions, 
                                          "destinationOne",   "destinationOneRegion")
    meta_df = classify_destination_column(meta_df, regions, 
                                          "destinationTwo",   "destinationTwoRegion")
    meta_df = classify_destination_column(meta_df, regions, 
                                          "destinationThree", "destinationThreeRegion")

    return meta_df

def analyze_destinations(meta_df):
    '''Parse and edit destinations from ship metadata'''
    locodes = load_port_data()
    meta_df = match_port_identifiers(meta_df, locodes) # NOTE: Contains in-place editing of locodes-dataframe

    locodes = classify_regions(locodes, "Latitude", "Longitude", "PortLocation")
    meta_df = classify_destination_regions(meta_df, locodes[["Country", 
                                                             "Location", 
                                                             "PortLocation"]].copy())

    return meta_df

 ###########################
#     General processing    #
 ###########################

def next_year(dt):
        '''Set datetime one year ahead'''
        
        try:
           return dt.replace(year=dt.year+1)
        except ValueError:
           # February 29th in a leap year
           # Add 365 days instead to arrive at March 1st
           return dt + timedelta(days=365)

def eta_to_datetime(eta):
    '''Convert digitraffic AIS ETAs to datetime
    
       Digitraffic stores ETA as an integer (e.g. 557760) 
       that when converted to binary encodes the date and time as such:
       
       Bits 19-16:  month; 1-12;  0 = not available = default 
       Bits 15-11:    day; 1-31;  0 = not available = default 
       Bits  10-6:   hour; 0-23; 24 = not available = default 
       Bits   5-0: minute; 0-59; 60 = not available = default'''

    if(eta == 1596): # All default / not available (00/00 24:60 MM/DD HH:MM)
        return None

    eta_bin = format(eta, '0b').zfill(20)
    
    eta_min = int(eta_bin[ -6:   ], 2) % 60 # Set default/NA to 0 for datetime conversion
    eta_hr  = int(eta_bin[-11: -6], 2) % 24 # Set default/NA to 0 for datetime conversion
    eta_day = int(eta_bin[-16:-11], 2)
    eta_mth = int(eta_bin[-20:-16], 2)

    # Probably unnecessary but better safe than sorry:
    if(eta_mth == 0 or eta_day == 0): 
        return None
    # Consider perhaps defaulting to today/tomorrow, but that seems risky

    # Check if ETA STILL bad (e.g. 31st September...)
    try:
        eta_datetime = datetime(datetime.now().year, eta_mth, eta_day, eta_hr, eta_min)
    except Exception as e:
        """ print("Bad ETA: ", eta, " = ", datetime.now().year, "/", eta_mth, "/", eta_day, 
              eta_hr, ":", eta_min) """
        return None

    # Simple check if ETA is e.g. from this year's December to next year's January
    if(eta_datetime < datetime.now() - timedelta(days=180)):
        eta_datetime = next_year(eta_datetime)

    return eta_datetime

def collect_ships_locations(latitude, longitude, distance, since):
    '''Collect ships' location data into a dataframe from given location, distance and time'''

    # NOTE: Python timestamps in seconds, digitraffic in milliseconds
    current_timestamp = floor(datetime.now().timestamp()*1000)
    
    ship_collection = get_ships_locations(latitude, longitude, distance, since)
    ships = ship_collection["features"]

    ''' Example:
    ... 'features': ...
    'geometry': {'type': 'Point', 'coordinates': [22.949432, 59.821617]},
    'properties': {'mmsi': 209955000,
    'sog': 0.0,
    'cog': 57.2,
    'navStat': 5,
    'rot': 0,
    'posAcc': False,
    'raim': False,
    'heading': 258,
    'timestamp': 43,
    'timestampExternal': 1692345778776}'''
    
    ship_dict = [dict(ship['properties'], 
                     **{'longitude':ship['geometry']['coordinates'][0], 
                        'latitude' :ship['geometry']['coordinates'][1]}) 
                for ship in ships]

    df = pd.DataFrame.from_dict(ship_dict)
    df['locAPICallTimestamp'] = current_timestamp

    # Remove unnecessary columns:
    # Receiver autonomous integrity monitoring (RAIM) flag of electronic position fixing device
    # The second within the minute data was reported
    df = df.drop(["raim", "timestamp"], axis=1)
    
    # Rename timestamp column to a more descriptive name for merging tables later
    df = df.rename(columns={"timestampExternal": "locUpdateTimestamp"})

    # Replace default / not available values with NAs
    df = df.replace({'sog': 102.3, 
                     'cog': 360, 
                     'rot': -128, 
                     'heading': 511}, np.NaN)
    
    df = classify_regions(df, "latitude", "longitude", "shipRegion")

    return df

def collect_specific_ships_locations(mmsi_list):
    '''Collect ships' location data into a dataframe from given list of mmsis'''
    # NOTE: Python timestamps in seconds, digitraffic in milliseconds
    current_timestamp = floor(datetime.now().timestamp()*1000)
    
    ships = []
    for mmsi in mmsi_list:
        ship_collection = get_ship_location(mmsi)
        ships += ship_collection["features"]

    ''' Example:
    ... 'features': ...
    'geometry': {'type': 'Point', 'coordinates': [22.949432, 59.821617]},
    'properties': {'mmsi': 209955000,
    'sog': 0.0,
    'cog': 57.2,
    'navStat': 5,
    'rot': 0,
    'posAcc': False,
    'raim': False,
    'heading': 258,
    'timestamp': 43,
    'timestampExternal': 1692345778776}'''
    
    ship_dict = [dict(ship['properties'], 
                     **{'longitude':ship['geometry']['coordinates'][0], 
                        'latitude' :ship['geometry']['coordinates'][1]}) 
                for ship in ships]

    df = pd.DataFrame.from_dict(ship_dict)
    df['locAPICallTimestamp'] = current_timestamp

    # Remove unnecessary columns:
    # Receiver autonomous integrity monitoring (RAIM) flag of electronic position fixing device
    # The second within the minute data was reported

    df = df.drop(["raim", "timestamp"], axis=1)
    
    # Rename timestamp column to a more descriptive name for merging tables later
    df = df.rename(columns={"timestampExternal": "locUpdateTimestamp"})

    # Replace default / not available values with NAs
    df = df.replace({'sog': 102.3, 
                     'cog': 360, 
                     'rot': -128, 
                     'heading': 511}, np.NaN)
    
    df = classify_regions(df, "latitude", "longitude", "shipRegion")

    return df

def collect_ships_meta(since):
    '''Collect ships' metadata into a dataframe since given time'''

    # NOTE: Python timestamps in seconds, digitraffic in milliseconds
    current_timestamp = floor(datetime.now().timestamp()*1000)
    
    ships = get_ships_meta(since)

    ''' Example:
    {'name': 'JOHANNA HELENA',
    'timestamp': 1692414605620,
    'mmsi': 209955000,
    'callSign': '5BMF5',
    'imo': 9372212,
    'shipType': 70,
    'draught': 55,
    'eta': 563840,
    'posType': 1,
    'referencePointA': 96,
    'referencePointB': 19,
    'referencePointC': 8,
    'referencePointD': 8,
    'destination': 'SE OXE'}'''

    df = pd.DataFrame.from_dict(ships)
    df['metaAPICallTimestamp'] = current_timestamp

    # Remove unnecessary columns:
    # Vessel International Maritime Organization (IMO) number
    # Type of electronic position fixing device (GPS, GLONASS, etc.)
    # GNSS antenna position reference

    # NOTE: MMSI changes with e.g. nationality, whereas IMO is static. 
    #       We use MMSI because so does digitraffic

    df = df.drop(["imo", "posType",
                  "referencePointA", "referencePointB",
                  "referencePointC", "referencePointD"], axis=1)

    # Replace default / not available values with NAs
    df = df.replace({'draught': 0}, np.NaN)
    
    # Rename timestamp column to a more descriptive name for merging tables later
    df = df.rename(columns={"timestamp": "metaUpdateTimestamp"})

    # Fix formatting of ETA from integer to datetime
    cutoff = datetime.now() - timedelta(days=30)
    cutoff_timestamp = floor(cutoff.timestamp()*1000)
    # Set ETA for metadata updated over a month ago to NA
    df.loc[(df["metaUpdateTimestamp"] < cutoff_timestamp), "eta"] = 1596
    df["eta"] = df["eta"].apply(eta_to_datetime)

    return df

#############################
#     Database handling     #
#############################

def create_connection(db_file):
    '''Create a database connection to a SQLite database'''

    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        print(e)
    
    return conn

def append_table(db_connection, dataframe, table):
    '''Append a dataframe to a database table'''

    if db_connection is not None:
        dataframe.to_sql(table, db_connection, if_exists="append", index=False)
    else:
        print("Error! cannot create the database connection.")

def drop_table(db_connection, table):
    '''Drop a table from a database'''
    # Mainly meant to be a development tool
    cursor = db_connection.cursor()

    cursor.execute(f'DROP TABLE {table}')
    db_connection.commit()

def delete_duplicate_rows(db_connection, table, columns):
    '''Delete duplicate rows from a database table'''

    sql_command = f'DELETE FROM {table} WHERE rowid NOT IN (SELECT MIN(rowid) FROM {table} GROUP BY {columns})'
    sql_cursor = db_connection.cursor()
    sql_cursor.execute(sql_command)
    db_connection.commit()

def delete_old(db_connection, table, column, timestamp):
    '''Delete rows from a database table with updatetime < given time'''

    sql_command = f'DELETE FROM {table} WHERE {column} < {timestamp}'
    sql_cursor = db_connection.cursor()
    sql_cursor.execute(sql_command)
    db_connection.commit()

def update_meta_table(db_connection, since): # TODO: In-depth QA
    '''Update database meta table with with data since last update'''
    meta_df = collect_ships_meta(since)
    meta_df = analyze_destinations(meta_df)

    # Simply create a table if one doesn't exist
    try:
        meta_df.to_sql("meta", db_connection, if_exists="fail", index=False)
        return
    except ValueError:
        pass

    # Create a temp table from the dataframe
    meta_df.to_sql("temp", db_connection, if_exists="replace", index=False)

    columns = list(meta_df.columns)

    # Insert whole row where the mmsi in dataframe isn't in table
    columns_string = ", ".join(columns)
    sql_insert_query = f'INSERT INTO meta ({columns_string}) SELECT {columns_string} FROM temp AS t '
    sql_insert_query += "WHERE NOT EXISTS (SELECT mmsi FROM meta AS sub WHERE sub.mmsi = t.mmsi);"

    # Update non-mmsi columns where mmsi in both dataframe and table
    columns.remove("mmsi")
    set_list = []
    for column in columns:
        set_list.append(f'{column} = temp.{column}')
    set_string = ", ".join(set_list)

    sql_set_query = f"UPDATE meta SET {set_string} FROM temp WHERE temp.mmsi = meta.mmsi;"

    # Perform queries
    cursor = db_connection.cursor()

    cursor.execute(sql_set_query)
    db_connection.commit()

    cursor.execute(sql_insert_query)
    db_connection.commit()

    # Remove the temp table
    cursor.execute("DROP TABLE temp")
    db_connection.commit()

def get_latest_meta_update_timestamp(db_connection):
    '''Get the latest update timestamp from meta table'''
    query = ("SELECT MAX(metaUpdateTimestamp) from meta")

    cursor = db_connection.cursor()

    cursor.execute(query)

    timestamp = cursor.fetchone()[0]
    return timestamp

def get_recent_threat_mmsi_list(db_connection, recency_cutoff_timestamp):
    '''Get the mmsis of ships recently classified as threats'''
    
    query = ("SELECT mmsi FROM (" 
                "SELECT *, ROW_NUMBER() OVER(PARTITION BY mmsi ORDER BY locAPICallTimestamp DESC) AS rownum FROM threats"
            ") latest_threats "
            "WHERE latest_threats.rownum = 1 "
            f" AND locAPICallTimestamp > {recency_cutoff_timestamp}")                    
    
    mmsi_list = pd.read_sql_query(query, db_connection)
    mmsi_list = mmsi_list["mmsi"].tolist()

    return mmsi_list