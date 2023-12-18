import folium
import folium.plugins as plugins

map_center = [61.55, 19.6]

map = folium.Map(location=map_center, zoom_start=9, tiles=None)

folium.TileLayer(tiles='openstreetmap', name='OpenStreetMap').add_to(map)

# Overlay for cargo ship traffic density, default off
folium.WmsTileLayer(url = "https://ows.emodnet-humanactivities.eu/geoserver/emodnet/ows?service=WMS", 
                    layers="emodnet:vesseldensity_allavg", 
                    fmt="image/png",
                    transparent = True,
                    attr='EMODNET-Human Activities and CLS', 
                    maxZoom = 20,
                    minZoom = 3,
                    show=False,
                    name="EMODNET Cargo vessel traffic density").add_to(map)

plugins.FloatImage("https://ows.emodnet-humanactivities.eu/geoserver/emodnet/wms?service=WMS&request=GetLegendGraphic&layer=emodnet:vesseldensity_allavg&format=image/png", 
                   bottom=40, left=65).add_to(map)

map.save('test.html')