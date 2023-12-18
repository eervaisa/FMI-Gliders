python "./AIS Map/Glider Data Processing/parse2.py" "./AIS Map/Map Data/Gliders" uivelo current_positions.json 20231108 >> "./AIS Map/Crontab/Logs/crontab_logs_uivelo_2.log" 2>&1
python "./AIS Map/Glider Data Processing/parse2.py" "./AIS Map/Map Data/Gliders" koskelo current_positions.json 20231108 >> "./AIS Map/Crontab/Logs/crontab_logs_koskelo_2.log" 2>&1
python "./AIS Map/Glider Data Processing/update_glider_wpts_json.py" "./AIS Map/Map Data/Gliders" archive glider_waypoints.json uivelo >> "./AIS Map/Crontab/Logs/crontab_logs_uivelo.log" 2>&1
python "./AIS Map/Glider Data Processing/update_glider_wpts_json.py" "./AIS Map/Map Data/Gliders" archive glider_waypoints.json koskelo >> "./AIS Map/Crontab/Logs/crontab_logs_koskelo.log" 2>&1
