NOTE: Required downloads: 
UpdatedPub150.csv from https://msi.nga.mil/Publications/WPI 
code-list_csv.csv from https://datahub.io/core/un-locode
Make sure you're in the Map Data/Ports directory, 
or adjust their paths in Digitraffic_To_SQLite_functions.py

Also note that fishing vessels are not found in the AIS data as per EU regulations, 
see discussion here: https://groups.google.com/g/meridigitrafficfi/c/4SVoBmZgFbM/m/tBnbU9eABgAJ

The glider popup graphs can be controlled with click-drag, scroll-zoom and reset with double-click.

When clicking a ship, its range, previous path and predicted path will be shown.
The range circle can be removed by double-clicking it.

The necessary packages can be installed in your active python environment using the map_requirements.txt file:
pip install -r map_requirements.txt

Alternatively you can create a new environment, potentially for new features or fixes to the packages
(such as when this project was originally created, the compatible version of Folium had a bugged measurement tool).

To create a conda environment capable of running all the script files, use the following commands:
conda create -n your_env_name_here
conda activate your_env_name_here
conda config --env --add channels conda-forge
conda config --env --set channel_priority strict
conda install python=3 geopandas altair

For the notebooks you'll also need:
pip install ipykernel ipynb

initialize_ais_database.py
    Run to initialize the SQLite database: gets ALL possible metadata (since 2018-01-01)
    and location data from given timestamp (datetime.now() - timedelta(hours=12, minutes=0)).
    Should only be ran once when creating the database - 
    initializing more than once should not cause errors, but is a waste of resources.

    Parameters to edit:
        latitude, longitude, distance, since
        - Determine where and when to get location data from

        initialization_timestamp
        - Determines the time where metadata initialized from (2018-01-01 contains all as of 2023).
          Necessary due to potentially having an old ship without updated metadata appearing 
          and forcing constant updates in draw_map. Therefore not recommended to edit.

        database
        - Name of the SQLite file. Remember to change in all other scripts as well!
    
    Call arguments:
        .../your_env_name_here/bin/python 
        .../initialize_ais_database.py 
        since_hrs 
        database

    Example call:
    .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/initialize_ais_database.py" 12 ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite"

update_meta.py
    Run to update the metadata table ("meta") in the database. Recommend e.g. every 6hrs.
    Automatically finds when last update was made and finds changes since then.
    Updates values for MMSIs already in the database and adds new rows for those that aren't.
        Contains commented out code for appending everything instead, but this is untested and 
    likely to break things, so not recommended - you should at least save to a table other than
    "meta" if you use this feature.

    Parameters to edit:
        database
        - Name of the SQLite file. Remember to change in all other scripts as well!

    Call arguments:
        .../your_env_name_here/bin/python 
        .../update_meta.py 
        database

    Example call:
    .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/update_meta.py" ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite"

update_locations.py
    Run to update the locations table ("locations") in the database, delete sufficiently old location data 
    from the database, draw a new map and update the "meta" table as well if any MMSIs in "locations" 
    aren't found in "meta". Recommend e.g. every hour or 30 mins. New values in "locations" are simply 
    appended and the previous map is simply replaced.

    Parameters to edit:
        latitude, longitude, distance, since
        - Determine where and when to get location data from, recommend "since" to be slightly higher than
          update interval (e.g. if update_locations.py run every hour, since = datetime.now() - timedelta(hours=1, minutes=30))

        time_cutoff_dt
        - Determines how old data should be discarded from the "locations" table.

        map_longitude, map_latitude, map_center
        - Determine where the map defaults to when first loaded. 
          If there are glider locations known, should default to latest of those instead however.

        database
        - Name of the SQLite file. Remember to change in all other scripts as well!

        vip_ships
        - Specific ships to classify outside normal classification (e.g. Aranda). Remember to change update_threats.py to use them as well!
        
        root_dir, map_filename
        - Directory and filename to save the map to. Remember to change update_threats.py to use them as well!
    
    Call arguments:
        .../your_env_name_here/bin/python 
        .../update_locations.py
        since_hrs 
        database
        root_dir
        map_filename

    Example call:
    .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/update_locations.py" 1 ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite" ".../FMI Gliders/AIS Map/Map Data" AIS_map.html

update_threats.py
    Run to update the locations of sufficiently recent threats in the "locations" table and draw a new map.
    If there are no sufficiently recent threats, do nothing instead. Recommend every 10 mins or so. New values 
    in "locations" are simply appended and the previous map is simply replaced. Makes an API call for each MMSI 
    individually which can be slow, so let's hope there aren't ever a lot at once!

    Parameters to edit:
        recency_cutoff
        - Determines how old threats should be ignored. Recommend slightly higher than script run interval
          (e.g. if update_threats.py run every 10 mins, recency_cutoff = datetime.now() - timedelta(minutes=15))

        latitude, longitude, distance, since
        - Determine where and when to get location data from, recommend to match update_locations.py.

        map_longitude, map_latitude, map_center
        - Determine where the map defaults to when first loaded. 
          If there are glider locations known, should default to latest of those instead however.

        database
        - Name of the SQLite file. Remember to change in all other scripts as well!

        vip_ships
        - Specific ships to classify outside normal classification (e.g. Aranda). Remember to change update_locations.py to use them as well!
        
        root_dir, map_filename
        - Directory and filename to save the map to. Remember to change update_locations.py to use them as well!   
        
    Call arguments:
        .../your_env_name_here/bin/python 
        .../update_threats.py
        since_hrs 
        database
        recency_cutoff_mins
        root_dir
        map_filename

    Example call:
    .../your_env_name_here/bin/python ".../FMI Gliders/AIS Map/Map Scripts/update_threats.py" 1 ".../FMI Gliders/AIS Map/Map Data/AIS.sqlite" 15 ".../FMI Gliders/AIS Map/Map Data" AIS_map.html

Digitraffic_To_SQLite_functions.py
    Contains the functions necessary for performing the Digitraffic API calls, processing the data and saving it into
    the database ("locations" and "meta" tables).
    
    Relevant parameters to edit:
        HEADERS
            - Used in Digitraffic API calls to track errors/loads as requested in their guidelines.
              Suggested format of {'Digitraffic-User': 'Your-username-here/Your-projectname-here'}
              Don’t send any PII (personally identifiable information) via the headers!
              For more info see: https://www.digitraffic.fi/en/support/instructions/#general-considerations

        get_ships_meta()
        get_ship_meta()
        get_ships_locations()
        get_ship_location()
            API call URLs should Digitraffic ever change them

        collect_ships_meta()
        collect_ships_locations()
        collect_specific_ships_locations()
            What data should be retrieved and in what format

        eta_to_datetime()
            ETA formatting and invalid value handling

        classify_regions()
            Classification regions and their borders

        load_port_data()
            Path to code-list_csv.csv
            Which rows/columns to include/drop

        world_port_index_coordinate_updates()
            Path to UpdatedPub150.csv

        format_port_identifiers()
            Regex for alternate names used for ports in AIS data
            Handling of duplicate port names
        
        match_port_names()
            Regex for alternate names used for ports in AIS data

        manual_coordinate_updates()
        manual_port_additions()
            Manually add missing port data

Draw_Map_functions.py
    Contains the functions necessary for loading data from the database, updating it if necessary, processing it for 
    map drawing, drawing the map and saving data of any ships classified as threats (load from "locations" and "meta",
    update "meta", save to "threats"). Also uses some functions from Digitraffic_To_SQLite_functions.py.
        If there are no active gliders, an IOError message will be printed and the map will only have the ships categorized 
    by the region they are in. This is done because drawing all ship markers at once is bad for performance - with the 
    category layers you can look at just the regions that interest you.
        Note: every script that checks for missing metadata using check_missing_meta function will print a message if there's
              still missing metadata after updating (i.e. "Some metadata still missing after update, try again later")

    Relevant parameters to edit:
        load_glider_data()
            interesting_sensors
                - Glider sensors used in the map.

        load_glider_sensors()
            Path to current_positions.json

        load_glider_waypoints()
            Path to glider_waypoints.json

        get_path()
            interval_duration
            path_duration
                - Determine how ships' predicted paths are calculated
            Condition for only drawing a circle
            Condition for limiting turning

        classify_ships()
            Conditions for ship classification
            Ship classification levels

        process_no_gliders_ship_data()
            ships_df['tooltip_html']
                - HTML used for creating popups when clicking ships

        process_ship_data()
            ships_df['tooltip_html']
                - HTML used for creating popups when clicking ships
            Marker colours
        
        save_dangerous_ship_data()
            dangerous_ships
                - Which ships to save data from
                - What data to save from those ships
            append_table(...)
                - Which table to save that data in

        extrapolate_glider_battery()
            Which variables to extrapolate and to what target point
                - Make sure they're in interesting_sensors given in load_glider_data()!
            Relevant variable information to be used in create_glider_popup_chart() (e.g. units for axis titles)
        
        extrapolate_variables()
            How the extrapolation of variables given in extrapolate_glider_battery() is performed
            gradient_timeframe
                - Length of the timeframe for calculating the average rate of change for the variables (e.g. 12h since last data point)

        create_glider_popup_chart()
            Glider popup chart visuals (axes, titles etc.)

        add_glider_markers()
            Link to glider icon
            Glider range circle
            Glider path and plan popups etc.
        
        add_ship_markers()
            Ship layer names
            Ship marker parameters
                - Especially popup size
            Adding ships to layers

        add_no_gliders_ship_markers()
            Ship layer names
            Ship marker parameters
                - Especially popup size
            Adding ships to layers
      
!!!!  add_aranda_plan() !!!!HIGH PRIORITY!!!!
            Expected to change often, keep up to date!
                - If data isn't found or is out of date, that's fine, 
                    but changing the data's format without taking it into account here can break everything!
            Path to the plan data (waterexchange.csv as of Water Exchange 2023)
            Formatting depending on data
                - As of Water Exchange 2023, the data was extremely messy, so there's a lot of data clean up done here
            Marker popup HTML
            Marker parameters
                - Especially popup size

        add_tile_layers()
            Map tile layers and their parameters (e.g. transparency, attribution, layer name in selector etc.)

        add_map_tools()
            Various interactive map tools and their parameters (e.g. drawing, layer control and their locations on the screen)

        add_deployment_info()
            Info textbox contents and style (e.g. text and background colour and opacity)
            Link to deployment_positions.json

mission_end_cleanup.py
    After a glider mission ends and it has been retrieved, this script can remove all now unnecessary data from that mission.
    First edit the following parameters in main():

        glider
            - The name of the glider whose mission ended (in lowercase)
        mission_end
            - The datetime for the end of the mission/glider retrieval

    If necessary also edit:
        database
            - The filepath to the sqlite database with the relevant "threats" table
        json_root
            - The filepath to the directory with the json files you want to edit
        archive_root
            - The filepath to the directory with the goto and yo files

    Also edit the json file names in the read_json_remove_glider() calls in main() if necessary.

    Then call the script with e.g.:
    /opt/usr/local/anaconda3/envs/AIS_maps/bin/python $HOME/src/glider/AIS_map/mission_end_cleanup.py

Digitraffic_To_SQLite.ipynb
    Contains the same functions as Digitraffic_To_SQLite_functions.py, useful for testing and development.

Draw_Map.ipynb
    Contains the same functions as Draw_Map_functions.py, useful for testing and development.