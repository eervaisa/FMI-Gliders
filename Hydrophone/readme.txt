You can install the necessary packages for these files using the glider_requirements.txt file:
pip install -r glider_requirements.txt

Notice that dbdreader may have issues installing on Windows, check
https://github.com/smerckel/dbdreader 
and consider installing it manually separately instead.

noise_analysis.ipynb
    Creates the dataset containing glider noise, passing ships and wind 
    used by noise_visualisation.ipynb and noise_timeline_animation.ipynb.
    Also has prototypes for visualisations in noise_visualisation.ipynb.

noise_timeline_animation.ipynb
    Contains (animated) visualisations of the data created by 
    noise_analysis.ipynb on a timeline. Note that the data should be 
    limited to a fairly short timeframe, e.g. 15 minutes.

noise_visualisation.ipynb 
    Contains 3D visualisations of the data created by noise_analysis.ipynb.