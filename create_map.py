#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Volker Fröhlich, 2013
# volker27@gmx.at

"""
Creates a Zabbix map from a Dot file
zbximage and hostname are custom attributes that can be attached to nodes.
Nodes with a hostname attribute are considered Zabbix hosts and looked up
for. Other nodes are treated as images. zbximage and label can be used there.
Edges have their color and label attributes considered.

This script is meant as an example only!
"""

# Curly brace edge notation requires a patched networkx module
# https://github.com/networkx/networkx/issues/923

import logging
import networkx as nx
import optparse
import sys
from pyzabbix import ZabbixAPI, ZabbixAPIException
import matplotlib.pyplot as plt

parser = optparse.OptionParser()
parser.add_option('-u', '--username', help="Username", default="admin")
parser.add_option('-p', '--password', help="Password", default="zabbix")
parser.add_option('-s', '--host', help="Host To talk to the web api", default="localhost")
parser.add_option('-d', '--path', help="Path", default="/zabbix/")
parser.add_option('-f', '--mapfile', help=".dot graphviz file for imput", default="data.dot")
parser.add_option('-g', '--graphview', help="show graph on screen y/[n]", action="count", default=0)
parser.add_option('-n', '--mapname', help="Map name to put into zabbix")
parser.add_option('-r', '--protocol', help="Protocol to be used", default="http")
parser.add_option('-v', '--verbosity', help="control logging", action="count", default=0)
(options,args)=parser.parse_args()

if not options.mapname:
	print("Must have a map name!")
	parser.print_help()
	sys.exit(-1)

if options.verbosity > 0:
    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.DEBUG)
    log = logging.getLogger('pyzabbix')
    log.addHandler(stream)
    log.setLevel(logging.DEBUG)

width = 1920
height = 1280

ELEMENT_TYPE_HOST = 0
ELEMENT_TYPE_MAP = 1
ELEMENT_TYPE_TRIGGER = 2
ELEMENT_TYPE_HOSTGROUP = 3
ELEMENT_TYPE_IMAGE = 4

ADVANCED_LABELS = 1
LABEL_TYPE_LABEL = 0

#TODO: Available images should be read via the API instead
#icons = {
    #"router": 130,
    #"cloud": 26,
    #"desktop": 27,
    #"laptop": 28,
    #"server": 106,
    #"database": 20,
    #"sat": 30,
    #"tux": 31,
    #"default": 40,
    #"house":34
#}

colors = {
    "purple": "FF00FF",
    "green": "00FF00",
    "default": "00FF00",
}

def icons_get():
    icons = {}
    iconsData = zapi.image.get(output=["imageid","name"])

    for icon in iconsData:
        icons[icon["name"]] = icon["imageid"]
    # print("icons {}".format(icons))

    return icons

def api_connect():
    zapi = ZabbixAPI(options.protocol + "://" + options.host + options.path)
    zapi.login(options.username, options.password)

    return zapi

def host_lookup(hostname):
    hostid = zapi.host.get(filter={"host": hostname})

    # print("hostname {} id {}".format(hostname, hostid))

    if hostid:
        return str(hostid[0]['hostid'])

    print("Missing hostid for hostname {}".format(hostname), file=sys.stderr)

    return None

def map_lookup(mapname):
    mapid = zapi.map.get(filter={"name": mapname})

    # print("mapid {} id {}".format(mapname, mapid))

    if mapid:
        return str(mapid[0]['sysmapid'])

################################################################

# Convert your dot file to a graph
G=nx.drawing.nx_agraph.read_dot(options.mapfile)

# Use an algorithm of your choice to layout the nodes in x and y
pos = nx.drawing.nx_agraph.graphviz_layout(G)

# Find maximum coordinate values of the layout to scale it better to the desired output size
#TODO: The scaling could probably be solved within Graphviz
# The origin is different between Zabbix (top left) and Graphviz (bottom left)
# Join the temporary selementid necessary for links and the coordinates to the node data
poslist=list(pos.values())
maxpos=list(map(max, zip(*poslist)))

# print(pos.items())

for host, coordinates in pos.items():
   pos[host] = [int(coordinates[0]*width/maxpos[0]*0.65-coordinates[0]*0.1), int((height-coordinates[1]*height/maxpos[1])*0.65+coordinates[1]*0.1)]
# print(pos.items())
nx.set_node_attributes(G,name='coordinates',values=pos)

selementids = dict(enumerate(G.nodes(), start=1))
selementids = dict((v,k) for k,v in selementids.items())
nx.set_node_attributes(G,name='selementid',values=selementids)

# Prepare map information
map_params = {
    "name": options.mapname,
    "label_format": ADVANCED_LABELS,
    "label_type_image": LABEL_TYPE_LABEL,
    "width": width,
    "height": height
}
element_params=[]
link_params=[]

zapi = api_connect()
icons = icons_get()


# Prepare node information

for node, data in G.nodes(data=True):
    # print("node {} data {}".format(node,data))
    # Generic part
    map_element = {}
    map_element.update({
            "selementid": data['selementid'],
            "x": data['coordinates'][0],
            "y": data['coordinates'][1],
            "use_iconmap": 0,
            })

    if "hostname" in data:
        map_element.update({
                "elementtype": ELEMENT_TYPE_HOST,
                "elements": [{"hostid":
                    host_lookup(data['hostname'].strip('"'))}],
                "iconid_off": icons['Rackmountable_2U_server_3D_(128)'],
                })
    elif "map" in data:
        map_element.update({
		"elementtype": ELEMENT_TYPE_MAP,
		"elementid": map_lookup(data['map'].strip('"')),
                "iconid_off": icons['Cloud_(96)'],
                })

    else:
        map_element.update({
            "elementtype": ELEMENT_TYPE_IMAGE,
            "elementid": 0,
        })
    # Labels are only set for images
    # elementid is necessary, due to ZBX-6844
    # If no image is set, a default image is used

    if "label" in data:
        map_element.update({
            "label": data['label'].strip('"')
        })

    if "zbximage" in data:
        map_element.update({
            "iconid_off": icons[data['zbximage'].strip('"')],
        })
    elif "hostname" not in data and "zbximage" not in data:
        map_element.update({
            "iconid_off": icons['Cloud_(96)'],
        })
    # print(map_element)

    element_params.append(map_element)

# Prepare edge information -- Iterate through edges to create the Zabbix links,
# based on selementids
nodenum = nx.get_node_attributes(G,'selementid')

for nodea, nodeb, data in G.edges(data=True):
    link = {}
    link.update({
        "selementid1": nodenum[nodea],
        "selementid2": nodenum[nodeb],
        })

    if "color" in data:
        color =  colors[data['color'].strip('"')]
        link.update({
            "color": color
        })
    else:
        link.update({
            "color": colors['default']
        })

    if "label" in data:
        label =  data['label'].strip('"')
        link.update({
            "label": label,
        })

    link_params.append(link)

# Join the prepared information
# print("map_params {}".format(map_params))
map_params["selements"] = element_params
# print("map_params {}".format(map_params))
map_params["links"] = link_params
# print("map_params {}".format(map_params))

# Get rid of an existing map of that name and create a new one
del_mapid = zapi.map.get(filter={"name": options.mapname})

if del_mapid:
	zapi.map.update({"sysmapid":del_mapid[0]['sysmapid'], "links":[], "selements":[], "urls":[] })
	map_params["sysmapid"] = del_mapid[0]['sysmapid']
	#del map_params["name"]
	#del map_params["label_format"]
	#del map_params["label_type_image"]
	#del map_params["width"]
	#del map_params["height"]
	map=zapi.map.update(map_params)
else:
    # print("create map {}".format(map_params))
    try:
        map = zapi.map.create(map_params)
    except ZabbixAPIException as e:
        print("exception {}".format(e))

if options.graphview:
    nx.draw(G, cmap = plt.get_cmap('jet'))
    plt.show()   # draw on screen
