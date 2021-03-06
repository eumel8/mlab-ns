# Introduction

The M-Lab Naming Service (aka mlab-ns) is a distributed system based on Google AppEngine that ‘routes’ HTTP requests for tools hosted on M-Lab to the best server, according to different policies.

See the [Design Proposal document](https://docs.google.com/document/d/1HipWaHmbE6P0dW4eoZb1p5pC8vaWXG8fapau2d2Lfpg/edit#heading=h.eiygbtl1au15) for the original list of requirements for mlab-ns.

In a typical usage scenario, a user runs one of the measurement tools that are hosted on the M-Lab platform by clicking a link embedded within a web page or running a mobile app or a command-line app. The link points to the mlab-ns server hosted on Google AppEngine and includes the tool name within the path, e.g.:

> http://mlab-ns.appspot.com/ndt

When the request arrives to mlab-ns, the geolocation of the user is automatically included in the HTTP headers by the Google AppEngine infrastructure. Note that the user is not required to consent to this information being sent. Finally, using this information, mlab-ns selects the best M-Lab server (according to various metrics) and redirects the user to the corresponding URL.

## M-Lab Entities
![M-Lab Entities Chart](https://raw.githubusercontent.com/wiki/m-lab/mlab-ns/assets/images/mlab_ns-entities_chart.png)

A single slice can run more than one Tool (e.g., gt\_partha contains both pathload2 and shaperprobe).
A SliverTool is an instance of a specific tool running in a specific Sliver. 
A SliverTool can have 2 states
* Online, if it can serve traffic.
* Offline, if it cannot serve traffic.

# Architecture 

## SliverTool and Site DB

Every registered SliverTool has a corresponding entry in the SliverTool table.
The Site DB contains geolocation data of the M-Lab sites.

See the schema of both the tables in the [data model](https://github.com/m-lab/mlab-ns/blob/master/server/mlabns/db/model.py).

Google AppEngine uses a storage model (Google Cloud Datastore) that allows to easily change the database schema by adding or deleting attributes. As a consequence, it is possible to extend the schema later to add additional relevant fields (e.g. RTT, ISP).

For a complete snapshot of the current DB see: 
* http://mlab-ns.appspot.com/admin/sliver\_tools
* http://mlab-ns.appspot.com/admin/sites

## Detecting New Sites 

mlab-ns detects new sites through a cron job that runs once daily. It causes mlab-ns to query a current site list at the following URL:

* https://siteinfo.mlab-oti.measurementlab.net/v1/sites/locations.json

mlab-ns then compares checks if any new sites appear in this list, and if so, registers the new sites in the data store.

## Detecting Slice Availability Changes

mlab-ns is integrated with Prometheus, M-Lab’s monitoring system, to check which slivers are available. In particular, mlab-ns queries Prometheus every minute and updates the status of the slivers accordingly. The queries that mlab-ns issues to Prometheus can be [found in the code in the file prometheus\_status.py](https://github.com/m-lab/mlab-ns/blob/master/server/mlabns/util/prometheus\_status.py#L40).

## Detecting IP Address Changes

mlab-ns detects changes to M-Lab site IP addresses via a cron job that runs once daily. It fetches the file hostnames.json via the following URL:

* https://siteinfo.mlab-oti.measurementlab.net/v1/sites/hostnames.json

The file format is JSON, in the following format:

```
[
  {
    "hostname": [slice FQDN],
	"ipv4": [IPv4],
	"ipv6": [IPv6]
  },
  ...
]
```

Where each field is a separate object in the array. An example of partial results from this file is shown below.

```
{
   "hostname": "ndt.iupui.mlab2.ams03.measurement-lab.org",
   "ipv4": "80.239.169.24",
   "ipv6": "2001:2030:32::24"
},
{
   "hostname": "geoloc4.uw.mlab2.ams03.measurement-lab.org",
   "ipv4": "80.239.169.28",
   "ipv6": "2001:2030:32::28"
},
{
   "hostname": "ispmon.samknows.mlab2.ams03.measurement-lab.org",
   "ipv4": "80.239.169.30",
   "ipv6": "2001:2030:32::30"
},
{
   "hostname": "bismark.gt.mlab2.ams03.measurement-lab.org",
   "ipv4": "80.239.169.31",
   "ipv6": "2001:2030:32::31"
},
```

Using this information, mlab-ns adds sliver information to its data store (for previously unknown slivers) or updates the existing sliver entries in the data store (for previously added slivers).

## LookupHandler

The LookupHandler ‘routes’ HTTP requests for tools hosted on M-Lab to the best server, according to different policies. Based on the lookup arguments specified in the URL, the response can be:

* An HTTP redirect to the SliverTool’s URL
* An explicit response, whose body contains the SliverTool information (IPv4 address, IPv6 address, URL, …) encoded in a format specified in the request

### URL format

**GET http://mlab-ns.appspot.com/[tool-name]?[query_string]**

Supported arguments in query_string:

|  Parameter  |  Values  |  Default  |  Notes  |
|  ---------  |  ------  |  -------  |  -----------  |
|  policy  |  geo, geo_options, metro, random, country, all  |  geo  | See _policy - parameter options_ section below. |
|  metro  |  _Metro Code_  |  -  |  The SliverTool is selected only from the subset of the sites that match the specified metro attribute. If no server is found, an HTTP Not Found is returned to the client.  |
|  format  |  json, bt, html, map, redirect  |  json  |  e.g., with format=json,the handler sends a response whose body contains the SliverTool information (IPv4 address, IPv6 address, URL, …) encoded in the json format.  |
|  ip  |  _IP Address_  |  -  |  The request appears as if it was originated from the specified ip address. Note: This overrides the Google AppEngine header.  |
|  address_family  |  ipv4, ipv6  |  ipv4  |  Allows to specify the address family. When the user specifies an address_family=ipvX, only sliver tools that have status_ipvX='online' will be considered in the server selection. If there is no sliver tool in the requested address family, an error (not found) is returned.  |
|  country  |  _Country Code_  |  -  |  The request appears as if it was originated from the specified country. Note: This overrides the Google AppEngine header. Also note: The country code must be in capital letters.   |
|  city  |  _City Name_  |  -  |  The request appears as if it was originated from the specified city. Note: This overrides the Google AppEngine header. It must be used together with country (e.g., city=Rome&country=IT). Note that these location parameters (country, city, latitude, longitude) can be defined by M-Lab tool developers and can be arbitrary. They are useful when debugging queries to determine what mlab-ns would return for a user with this location.  |

#### policy - parameter options

* **geo** - Returns a single server based on geolocation of the user's IP. Example: `https://mlab-ns.appspot.com/ndt?policy=geo`
* **geo_options** - Chooses the N geographically closest servers to the client, where N is currently four.  Example: `https://mlab-ns.appspot.com/ndt?policy=geo_options`
* **metro** - Used in combination with the _metro_ parameter below, returns a single server in the selected metro. Used without _metro_, functions similarly to _policy=geo_.  Example: `https://mlab-ns.appspot.com/ndt?policy=metro&metro=lax`
* **random** - Selects a random server. Example: `https://mlab-ns.appspot.com/ndt?policy=random`
* **country** - Used in combination with the _country_ parameter, returns a single server from the selected country. Example: `https://mlab-ns.appspot.com/ndt?policy=country&country=CA`
* **all** - Returns a list of all currently available servers. Example: `https://mlab-ns.appspot.com/ndt?policy=all`

### Geo-based server selection policy
By default, mlab-ns selects a SliverTool using the ‘closest-node’ policy, which means that the user is directed to a server in the geographically closest site. The server is chosen each time randomly from the servers in the same site, to ensure fairness. The geolocation data of the client making the request is included automatically in the headers of the request by Google AppEngine infrastructure:

    self.request.headers['X-AppEngine-City']
    self.request.headers['X-AppEngine-Region']       
    self.request.headers['X-AppEngine-Country']
    self.request.headers['X-AppEngine-CityLatLong']

#### Unknown location

Sometimes Google AppEngine does not provide geolocation info for an incoming request. 
Nevertheless, mlab-ns still needs to provide an answer in such cases.

To address this issue, mlab-ns uses MaxMind's free GeoLite2 databases:
https://dev.maxmind.com/geoip/geoip2/geolite2/

Also, ISO 3166 country codes DB:
(from https://www.cia.gov/library/publications/the-world-factbook/fields/2011.html)

Namely, when latitude/longitude are missing from the Google AppEngine header:
If city and country are present in the Google AppEngine header, lat and lon are retrieved from db.MaxmindCityLocation.
If only country is present in the Google AppEngine header, lat and lon are retrieved from db.CountryCode.
If the Google AppEngine header does not have any location information, lat and lon are retrieved from db.MaxmindCityBlock using the user IP address.
Using these tables increases the lookup response time.

mlab-ns logs all the requests in which geolocation fails. Based on those logs, we may revisit the strategy above.

# Logging
mlab-ns logs all lookup requests using standard AppEngine logging.

# Monitoring
Maps with sliver status (ipv4/ipv6, broken down by tool): http://mlab-ns.appspot.com/admin/map/

# Privacy
[M-Lab NS Privacy Policy](MLAB-NS_PRIVACY_POLICY.md)

# Code repository
https://github.com/m-lab/mlab-ns

