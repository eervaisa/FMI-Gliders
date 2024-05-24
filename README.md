Collection of glider-related projects I created while working for the Finnish Meteorological Institute.

The necessary packages to run these projects can be installed in your active Python environment using 
their respective requirements.txt file:

pip install -r file_name_here

map_requirements is for the project in the AIS Map folder, glider_requirements for everything else.

Notice for glider_requirements that dbdreader may have issues installing on Windows 
(check https://github.com/smerckel/dbdreader) 
and consider removing it from the file and installing it manually, separately instead.
