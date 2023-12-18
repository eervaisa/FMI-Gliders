from datetime import datetime
from math import floor
import os
import sqlite3
import json

def read_json_remove_glider(json_root, json_file, glider):
    '''Read json and remove ALL glider data'''
    # read previous position list as json
    with open('{}/{}'.format(json_root, json_file), 'r') as file:
        json_data = json.load(file)
        file.close()
    
    try:
        del json_data[glider]
    except KeyError as e:
        # print(e)
        return

    with open('{}/{}'.format(json_root, json_file), 'w') as file:
        json.dump(json_data, file)
        file.close()

def read_json_remove_glider_by_date(json_root, json_file, glider, mission_end_string):
    '''Read json and remove glider data before given datetime'''
    # read previous position list as json
    with open('{}/{}'.format(json_root, json_file), 'r') as file:
        json_data = json.load(file)
        file.close()
    
    try:
        glider_data = json_data[glider]
    except KeyError as e:
        # print(e)
        return
    if(isinstance(glider_data, list)):
        json_data[glider] = [elem for elem in glider_data if elem["datetime"] > mission_end_string + "Z"]
    else:
        if(glider_data["datetime"] < mission_end_string + "Z"):
            del json_data[glider]

    with open('{}/{}'.format(json_root, json_file), 'w') as file:
        json.dump(json_data, file)
        file.close()

def delete_invalid_threats(db_connection, timestamp, glider):
    '''Delete rows from database threats table for a glider with updatetime > mission end time'''

    sql_command = f"DELETE FROM threats WHERE locAPICallTimestamp > {timestamp} AND glider_name = '{str.capitalize(glider)}'"
    sql_cursor = db_connection.cursor()
    sql_cursor.execute(sql_command)
    db_connection.commit()

def delete_gotos_and_yos(archive_root, mission_end_string):
    '''Delete invalid data after glider retrieval'''
    # Choose files before mission end
    files = [f for f in os.listdir(archive_root) if (f.split('_')[0] < mission_end_string)]

    # Delete files
    for file in files:
        os.remove(f"{archive_root}/{file}")

def check_latest_read_goto(log_root, mission_end_string, json_root, glider):
        with open(f'{log_root}/latest_read_goto.txt', 'r') as file:
            latest_read_goto = file.read()
            file.close()

        if(latest_read_goto.split('_')[0] < mission_end_string):
            read_json_remove_glider(json_root, "glider_waypoints.json", glider)


def main():
    '''Delete invalid data after glider retrieval'''
    glider = "uivelo"
    mission_end = datetime.strptime("2023-11-23 14:30:00", "%Y-%m-%d %H:%M:%S")
    timestamp = floor(mission_end.timestamp()*1000)

    database = "./AIS Map/Map Data/AIS.sqlite"
    json_root = "./AIS Map/Map Data/Gliders/JSONs"
    archive_root = f"./AIS Map/Map Data/Gliders/{glider}/archive"
    log_root = f"./AIS Map/Map Data/Gliders/{glider}/data"

    # Format datetime like goto and yo files
    mission_end_string = mission_end.strftime("%Y%m%dT%H%M%S")

    delete_gotos_and_yos(archive_root, mission_end_string)

    check_latest_read_goto(log_root, mission_end_string, json_root, glider)

    read_json_remove_glider_by_date(json_root, "current_positions.json", glider, mission_end_string)
    read_json_remove_glider_by_date(json_root, "deployment_positions.json", glider, mission_end_string)
    read_json_remove_glider_by_date(json_root, "last_positions.json", glider, mission_end_string)

    db_connection = sqlite3.connect(database)

    delete_invalid_threats(db_connection, timestamp, glider)

    db_connection.close()

if __name__ == "__main__":
    main()

# Change parameters in main to reflect end of mission, then run:
# python "./AIS Map/Map Scripts/mission_end_cleanup.py"