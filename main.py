import requests
import furl
import json
import json
import os

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS, PointSettings
from influxdb_client import Point

import logging
logging.basicConfig(filename='honeywell.log', 
                        format='%(levelname)s\t%(asctime)s\t%(message)s', 
                        datefmt='%Y%m%d %H:%M:%S',
                        level=logging.DEBUG)

with open("config.json","r") as config_file:
    config = json.load(config_file)

influx_config = config['Influx']

logging.debug("Creating InfluxDB Client")
influx_client = influxdb_client.InfluxDBClient(
   url=influx_config['url'],
   token=influx_config['token'],
   org=influx_config['org'],
   enable_gzip=True
)
def load_token():

    logging.debug("Loading Token")
    if os.path.exists("token.json"):
        with open("token.json", "r") as file:
            token = json.load(file)
    else:
        logging.error("Token does not exists. Exiting")
        raise ValueError()

    f = furl.furl("https://api.honeywell.com/oauth2/token")
    
    headers = {"Authorization": config['Honeywell']['authorization'],
                "Content-Type": "application/x-www-form-urlencoded"}

    body = f"grant_type=refresh_token&refresh_token={token.get('refresh_token')}"


    logging.info("Refreshing token...")
    response = requests.post(f.url, 
                    headers = headers,
                    data = body)

    if response.status_code != 200:
        raise KeyError()

    with open("token.json","w") as file:
        json.dump(response.json(), file, indent=2)

    return response.json()

token = load_token()

authheader = {"Authorization": f"Bearer {token.get('access_token')}"}

f  = furl.furl("https://api.honeywell.com/v2/locations")
f.args['apikey'] = config['Honeywell']['apikey']

logging.info("Requesting location from api")
resp = requests.get(f.url, headers = authheader)

locations = resp.json()[0]
locationID = locations['locationID']
deviceID = locations['devices'][0]["deviceID"]

logging.info("Requesting Info about Device from api")
f = furl.furl(f"https://api.honeywell.com/v2/devices/thermostats/{deviceID}")
f.args['apikey'] = config['Honeywell']['apikey']
f.args['locationId'] = locationID

resp = requests.get(f.url, headers = authheader)

thermostat = resp.json()

point_settings = PointSettings()
point_settings.add_default_tag("deviceId", thermostat.get("deviceID"))
point_settings.add_default_tag("deviceOsVersion", thermostat.get("deviceOsVersion"))
point_settings.add_default_tag("macID", thermostat.get("macID"))

influx_write_api = influx_client.write_api(write_options=SYNCHRONOUS, point_settings=point_settings)

measurements_of_interest = [
    {
        "name": "temperature_indoor",
        "data": int(thermostat.get("indoorTemperature"))
    },
    {
        "name": "temperature_outdoor",
        "data": int(thermostat.get("outdoorTemperature"))
    },
    {
        "name": "humidity_outdoor",
        "data": int(thermostat.get("displayedOutdoorHumidity"))
    },
    {
        "name": "mode_set",
        "data": thermostat.get("changeableValues").get("mode")
    },
    {
        "name": "setpoint_heat",
        "data": thermostat.get("changeableValues").get("heatSetpoint")
    },
    {
        "name": "setpoint_cool",
        "data": thermostat.get("changeableValues").get("coolSetpoint")
    },
    {
        "name": "mode", 
        "data": thermostat.get("operationStatus").get("mode")
    }, 
    {
        "name": "fan_request", 
        "data": thermostat.get("operationStatus").get("fanRequest")
    }, 
    {
        "name": "circulation_fan_request", 
        "data": thermostat.get("operationStatus").get("circulationFanRequest")
    } 
]

for measurement in measurements_of_interest:
    logging.debug(f"{measurement['name']}: {measurement['data']}")

records = [Point("hvac_status").field(el['name'], el['data']) for el in measurements_of_interest]

influx_write_api.write(bucket = influx_config['bucket'], record = records)
influx_write_api.flush()
# print(f"Wrote new data point {time.time()}")

# Log to Healthchecks.com
try:
    requests.get(config['Healthchecks']['url'], timeout=10)
except requests.RequestException as e:
    # Log ping failure here...
    print("Ping failed: %s" % e)

logging.info("\n\n\n")
