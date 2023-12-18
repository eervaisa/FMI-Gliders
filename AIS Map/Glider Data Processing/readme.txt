parse2.py
    Reads glider .log files and updates the deployment_positions.json, last_positions.json and current_positions.json files. 
    Ignores already read files by keeping a log (log_list.txt).

update_glider_wpts_json
    Reads glider goto files and updates glider_waypoints.json.
    Only reads latest goto file (based on file name) and only if it hasn't been read before - latest read file filename stored in latest_read_goto.txt