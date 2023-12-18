import os
import re
import json
import sys 

def convert_coordinates_ddmm_to_dddd(coord):
    '''Convert coordinates from degrees+minutes to degrees+decimals'''
    
    degs = coord//100
    mins = coord % 100

    return round(degs + mins/60, 5)

def main():
    '''Reads glider goto-files and creates a json'''
    '''
    Output json format example:
    {"uivelo": [[21.14017, 61.217], [20.89406, 61.19131], [20.5984, 61.08414], 
                [20.2527, 61.05087], [19.91074, 61.06881], [19.5784, 61.08343], 
                [19.57372, 61.08332], [19.43089, 60.96624], [19.50365, 60.57783]], 
    "koskelo": [[19.43089, 60.96624], [19.50365, 60.57783], [19.43089, 60.96624]]}
    '''
    # glider_names = ["uivelo", "koskelo"]
    # root_dir = "../Map Data/Gliders"
    # goto_dir = "archive"

    root_dir = sys.argv[1]
    goto_dir = sys.argv[2]
    filename = sys.argv[3]
    glider_name = sys.argv[4]

    glider_wpt_dict = {}

    # for glider_name in glider_names:
    # Get the latest goto file
    goto_files = list(filter(re.compile(".*goto.*").match, 
                                os.listdir(f"{root_dir}/{glider_name}/{goto_dir}")))
    latest_goto_name = sorted(goto_files)[-1]
    
    # Check if it's already been read
    try:
        with open(f'{root_dir}/{glider_name}/data/latest_read_goto.txt', 'r') as file:
            latest_read_goto = file.read()
            file.close()
            if(latest_read_goto == latest_goto_name):
                return
    except Exception:
        pass
    # Read the goto file contents
    with open(f"{root_dir}/{glider_name}/{goto_dir}/{latest_goto_name}", 'r') as f:
        latest_goto = f.read()

    glider_waypoints = re.findall(r"^\d[\d \t\.]*", latest_goto, re.MULTILINE)
    glider_waypoints = [wpt.split() for wpt in glider_waypoints]
    glider_waypoints = [[float(coord) for coord in wpt] for wpt in glider_waypoints]
    glider_waypoints = [[convert_coordinates_ddmm_to_dddd(coord) for coord in wpt] 
                        for wpt in glider_waypoints]

    # Check if waypoints loop, append first element to the end if they do
    legs_to_run = re.search(r"num_legs_to_run\(nodim\)\s*([-\d]+)", 
                            latest_goto).group(1)
    if (legs_to_run == "-1"):
        glider_waypoints.append(glider_waypoints[0])

    # Update json
    try:
        with open(f'{root_dir}/JSONs/{filename}', 'r') as file:
            glider_wpt_dict = json.load(file)
    except Exception:
        pass
    glider_wpt_dict[glider_name] = glider_waypoints

    with open(f'{root_dir}/JSONs/{filename}', 'w') as file:
        json.dump(glider_wpt_dict, file)

    # Update log
    with open(f'{root_dir}/{glider_name}/data/latest_read_goto.txt', 'w') as file:
        file.write(latest_goto_name)
        file.close()

if __name__ == "__main__":
    main()

# python "./AIS Map/Glider Data Processing/update_glider_wpts_json.py" "./AIS Map/Map Data/Gliders" archive glider_waypoints.json koskelo