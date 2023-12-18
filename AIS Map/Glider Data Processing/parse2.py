# -*- coding: utf-8 -*-
import datetime
import json
import os
import re
from copy import deepcopy
import sys


def file_exists_and_not_empty(file_path):
    return os.path.isfile(file_path) and os.path.getsize(file_path) > 0

def read_data_from_file(filename):
    """Reads the data from the given file.

    Args:
      filename: The name of the file to read.

    Returns:
      A string containing the data from the file.
    """

    with open(filename, 'r') as f:
        data = f.read()
    if len(data) > 0:
        return data
    else:
        raise ValueError('Empty file: ', filename)


def parse_datetime(datetime_str):
    """Parses a datetime from a string of the format "Curr Time: Thu Sep 28 10:45:32 2023 MT:    3697".

    Args:
      datetime_str: A string containing the datetime to parse.

    Returns:
      A datetime object representing the parsed datetime.
    """
    try:
        #print('1>',datetime_str.group())
        date_time_match = datetime_str
        # Match the date and time using a regular expression.
        # Check the type of the datetime_str variable.
        # if type(datetime_str) is not str:
        #     # Convert the datetime_str variable to a string.
        #     datetime_str = str(datetime_str)

        # date_time_match = re.search(r'Curr Time: (\w+)\s+(\w+)\s+(\d+)\s+(\d+:\d+:\d+)\s+(\d+)', datetime_str)
        # print('2>', date_time_match.group())
        
        date = int(date_time_match[2])
        time = date_time_match[3]
        year = int(date_time_match[4])
        month = datetime.datetime.strptime(date_time_match[1], '%b').month
        #day = int(date_time_match.group(1))
        hour = int(time[:2])
        minute = int(time[3:5])
        second = int(time[6:])

        # Create a datetime object.
        datetime_obj = datetime.datetime(year, month, date, hour, minute, second)

        return datetime_obj
    except Exception:
        raise ValueError('Parse time error')


def convert_ddmm_mmm_to_decimal_degrees(ddmm_mmm_coordinates):
    """Converts ddmm.mmm coordinates to decimal degrees.

    Args:
      ddmm_mmm_coordinates: A string containing the ddmm.mmm coordinates.

    Returns:
      A float containing the decimal degrees coordinates.
    """

    # Split the string by degrees, minutes, and seconds.
    tokens = ddmm_mmm_coordinates.split('.')

    # Convert the degrees, minutes, and seconds to floats.
    degrees = float(tokens[0][:-2])
    minutes = float(tokens[0][-2:]) + float('0.'+tokens[1])

    # Calculate the decimal degrees coordinates.
    decimal_degrees = round(degrees + minutes / 60, 5)

    return decimal_degrees


def parse_glider_data(data):
    """Parses the glider data from the given string.

    Args:
      data: A string containing the glider data.

    Returns:
      A dictionary containing the parsed data.
    """

    # Parse the vehicle name.
    vehicle_name_match = re.search(r'Vehicle Name: (\w+)', data)
    glider = vehicle_name_match.group(1)

    # Parse the mission name.
    mission_name_match = re.search(r'MissionName:(\w+)\.[Mm][Ii]', data)
    mission_name = None
    if(mission_name_match):
        mission_name = mission_name_match.group(1)

    # Parse the mission number.
    mission_num_match = re.search(r'MissionNum:([-\w]+)', data)
    mission_num = None
    if(mission_num_match):
        mission_num = mission_num_match.group(1)

    # Parse the date and time.
    date_time_match = re.findall(
        r'Curr Time:\s(\w+)\s+(\w+)\s+(\d+)\s+(\d+:\d+:\d+)\s+(\d+)', data)
    #print(date_time_match)
    # if date_time_match:
    #     print('Matched String:', date_time_match.group())
    # else:
    #     print('No match found.')
        

    if date_time_match:
        # Specify the datetime format
        datetime_format = '%Y-%m-%dT%H:%M:%SZ'
        try:
            for i,date_time in enumerate(date_time_match):
                # Parse into datetime object, then convert datetime object to string
                date_time_match[i] = parse_datetime(date_time).strftime(datetime_format)
        except Exception:
            raise ValueError('Time missing')

    # Parse the location.
    location_match = re.findall(
        r'DR  Location:\s+(\d+.\d+)\s+N\s+(\d+.\d+)\s+E\s+measured', data)
    for i,location in enumerate(location_match):
        latitude = convert_ddmm_mmm_to_decimal_degrees(location[0])
        longitude = convert_ddmm_mmm_to_decimal_degrees(location[1])
        location_match[i] = {
            'latitude': float(latitude),
            'longitude': float(longitude)
        }

    # Split the data into chunks by 'Curr Time'
    split_data = re.split(r'Curr Time',data)
    sensor_data_match = []
    for split in split_data:
        # Get all the sensor data in each chunk
        sensor_data_match.append(re.findall(r'sensor:(\w+)\(.*\)=([-\.\d]+)',split))
    # Remove anything before first 'Curr Time'
    sensor_data_match = sensor_data_match[1:]

    log_data = []

    for i in range(0,len(date_time_match)):
        parsed_data = {}
        parsed_data['mission_name'] = mission_name
        parsed_data['mission_num'] = mission_num
        parsed_data['datetime'] = date_time_match[i]
        parsed_data['location'] = location_match[i]
        parsed_data['sensors'] = {}
        
        for sensor_tuple in sensor_data_match[i]:
            sensor_name, sensor_value = sensor_tuple
            parsed_data['sensors'][sensor_name] = float(sensor_value)
        
        log_data.append(deepcopy(parsed_data))
        
    return glider, log_data

def overwrite_json_condition(json_file, json_data, new_data, key):
    '''Check if we should overwrite old json'''
    overwrite = True
    try:
        if(json_file == 'deployment_positions.json'):
            overwrite = (json_data[key]["datetime"] > new_data[key]["datetime"])
        elif(json_file == 'last_positions.json'):
            overwrite = (json_data[key]["datetime"] < new_data[key]["datetime"])
    except KeyError:
        pass
    return overwrite

def read_overwrite_json(dataroot, json_file, new_data):
    '''Read and if necessary, overwrite old json'''
    # read previous position list as json
    try:
        with open('{}/JSONs/{}'.format(dataroot, json_file), 'r') as file:
            json_data = json.load(file)
    except Exception:
        json_data = new_data
    else:
        # overwrite new data into dict
        for key in new_data.keys():
            if(overwrite_json_condition(json_file, json_data, new_data, key)):
                json_data[key] = new_data[key]

    with open('{}/JSONs/{}'.format(dataroot, json_file), 'w') as file:
        json.dump(json_data, file)
    
    return

def read_append_json(dataroot, glider, json_file, data):
    '''Read and append old json'''
    # read previous position list as json
    try:
        with open('{}/JSONs/{}'.format(dataroot, json_file), 'r') as file:
            full_data = json.load(file)
    except Exception as e:
        full_data = data
    else:
        # append new data into dict
        for key in data.keys():
            try:
                # if glider already in file
                full_data[key] += data[key]
            except KeyError as e:
                # if glider not yet in file
                full_data[key] = data[key]
                print('append error ', e, glider, key)

    # re-sort after appending and before writing to file
    try:
        full_data[glider] = sorted(full_data[glider], key=lambda x: x["datetime"])
    except Exception:
        pass

    with open('{}/JSONs/{}'.format(dataroot, json_file), 'w') as file:
        json.dump(full_data, file)
    
    return


def update_location(dataroot, glider, current_pos_file, start_mission):
    '''Update json file of the current position of a glider'''

    log_list_file = '{:}/{:}/data/log_list.txt'.format(dataroot, glider)
    len_start = len(start_mission)
    
    # Read list of previously handeled log-files    
    try:
    # Read the file and store each line as an element in a list
        with open(log_list_file, 'r') as file:
            log_list = file.readlines()
        if len(log_list) == 0:
            log_list = []
    except Exception as e:
        log_list = []
    else:
         log_list = sorted([line.strip() for line in log_list])
 
    # Read a list of logfiles to process
    log_dir = '{:}/{:}/logs/'.format(dataroot, glider) 
    l_temp = sorted([f for f in os.listdir(log_dir) if f not in log_list])
    try:           
        files = [f for f in os.listdir(log_dir) if                              # filenames in directory where: 
                            ('log' in f) &                                      # 1. filename contains 'log'
#                            (f.split('_')[1].split('T')[0] > start_mission) &   # 2. filename date > start_mission
                            (f.split('_')[1][0:len_start] > start_mission) &    # 2. filename date > start_mission
                            (f not in log_list)]                                # 3. filename isn't in log_list
        if len(files) == 0:
            raise ValueError('No new logfiles')
    except Exception as e:
        raise ValueError(e, ' logfiles error, ', glider, start_mission, len(files), l_temp[-3:])

    # OBS:
    # previous data should be read, this routine is called by glidername. If both on a missing data should not be deleted
    #     
    # # read previous position list as json
    # try:
    #     with open(filename, 'r') as file:
    #         curr_pos = json.load(dataroot+'/forweb/'+current_pos_file)
    #     print('Positioita: ', len(curr_pos), len(curr_pos[glider]))
    # except Exception:
    #     current_pos = new_data
    # else:
    #     for key, value in current_pos.items():
    #         try:
    #             a = len(value)  # Check if the value is even
    #         except Exception:
    #             current_pos[key] = []
    #         # append new data into dict
    #         current_pos[key].append(new_data[g])
    #
    # if josn is empty, reread all logs, otherwise only last onces
    # lets read all and rewrite all data
    # files = [f for f in files if ('log' in f) & (f.split('_')[1].split('T')[0] > start_mission)] # & \~(f in log_list)]
    # if len(files) == 0:
    #     raise ValueError('No new logs')
    
    files = sorted(files)

    # read new log-files
    new_data = {glider:[]}
    
    for f in files:
        try:
            data = read_data_from_file(log_dir+f)
        except Exception:
            continue
        # Parse the example data.
        try:
            glider, parsed_data = parse_glider_data(data)
        except Exception:
            continue

        # Append parsed data into new data
        try:
            new_data[glider] += parsed_data
        except KeyError:
            pass
            # Create new key if glider name different from the one given in arguments
            # new_data[glider] = []
            # new_data[glider].append(parsed_data)

    if new_data == {} :
        new_data[glider] = []
        raise ValueError('No new data')
    
    # for g, value in new_data:
    #     try:
    #         current_pos[g].append(new_data[g])
    #     except KeyError:
    #         current_pos[g] = []
    #         current_pos[g].append(new_data[g])

    # current_pos = {key: value.append(new_data[g]) for key, value in current_pos.items()}
    
    try:
        new_data[glider] = sorted(new_data[glider], key=lambda x: x["datetime"])
    except Exception:
        pass

    # Deployment and last positions should be for both(all) gliders, so at first read files, and then update & write
    # Mission's deployment coordinates and date
    deployment_positions = {}
    for key, value in new_data.items():
        deployment_positions[key] = value[0]  

    # latest position of glider    
    last_positions = {}
    for key, value in new_data.items():
        last_positions[key] = value[-1]  

    read_overwrite_json(dataroot, 'deployment_positions.json', deployment_positions)
    read_overwrite_json(dataroot, 'last_positions.json', last_positions)
    read_append_json(dataroot, glider, current_pos_file, new_data)

    # Open the parsed log list file in append mode and write the new rows
    with open(log_list_file, 'a') as file:
        for row in files:
            file.write(row + '\n')  # Append each row followed by a newline character

    return True


def main():
    '''Read files'''

    dataroot = sys.argv[1]
    glider = sys.argv[2]
    glider_positions = sys.argv[3]
    start_missions_date = sys.argv[4]
    try:
        current_pos = update_location(dataroot, glider, glider_positions, start_missions_date)
    except Exception as e:
        print(e)
        pass

    # else:
    #     with open('{}/JSONs/{}'.format(dataroot, glider_positions), 'w') as file:
    #         json.dump(current_pos, file)

    #print(current_pos)

if __name__ == "__main__":
    main()

    # startday = '20230927'
    # droot = 'koskelo/logs/'
    # glider_positions = 'current_positions.json'
    # python "./AIS Map/Glider Data Processing/parse2.py" "./AIS Map/Map Data/Gliders" koskelo current_positions.json 20231108