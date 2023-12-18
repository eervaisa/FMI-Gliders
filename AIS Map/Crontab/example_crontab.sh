*/5 * * * * sh "./AIS Map/Crontab/update_jsons.sh" > "./AIS Map/Crontab/Logs/update_jsons.log" 2>&1

# AIS map and data updating
55 */6 * * * python "../AIS Map/Map Scripts/update_meta.py" "../AIS Map/Map Data/AIS.sqlite"  >> "./AIS Map/Crontab/Logs/crontab_logs_AIS_maps.log" 2>&1
0,30 * * * * python "../AIS Map/Map Scripts/update_locations.py" 1 "../AIS Map/Map Data/AIS.sqlite" "../AIS Map/Map Data" AIS_map.html  >> "./AIS Map/Crontab/Logs/crontab_logs_AIS_maps.log" 2>&1
10,20,40,50 * * * * python "../AIS Map/Map Scripts/update_threats.py" 1 "../AIS Map/Map Data/AIS.sqlite" 15 "../AIS Map/Map Data" AIS_map.html  >> "./AIS Map/Crontab/Logs/crontab_logs_AIS_maps.log" 2>&1
