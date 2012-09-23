from django.utils import simplejson

from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

from mlabns.db import model
from mlabns.util import constants
from mlabns.util import message
from mlabns.util import util

import gflags
import logging

class AdminHandler(webapp.RequestHandler):
    def post(self):
        """Not implemented."""
        return util.send_not_found(self)

    def get(self):
        path = self.request.path.rstrip('/')
        valid_paths = [
            '/',
            '/admin',
            '/admin/sites',
            '/admin/sliver_tools',
            '/admin/map',
            '/admin/map/ipv4',
            '/admin/map/ipv4/all',
            '/admin/map/ipv4/glasnost',
            '/admin/map/ipv4/neubot',
            '/admin/map/ipv4/ndt',
            '/admin/map/ipv4/npad',
            '/admin/map/ipv6',
            '/admin/map/ipv6/all',
            '/admin/map/ipv4/glasnost',
            '/admin/map/ipv6/neubot',
            '/admin/map/ipv6/ndt',
            '/admin/map/ipv6/npad' ]

        if path not in valid_paths:
            return util.send_not_found(self)

        # http://mlab-ns.appspot.com/admin/sites
        if path == '/admin/sites':
            return self.site_view()

        # http://mlab-ns.appspot.com/admin/sliver_tools
        if path =='/admin/sliver_tools':
            return self.sliver_tool_view()

        # http://mlab-ns.appspot.com/admin
        # http://mlab-ns.appspot.com/admin/map
        if not path or path == '/admin/map':
            return self.redirect('/admin/map/ipv4/all')

        # http://mlab-ns.appspot.com/admin/map/ipv4
        if path == '/admin/map/ipv4':
            return self.redirect('/admin/map/ipv4/all')

        # http://mlab-ns.appspot.com/admin/map/ipv6
        if path == '/admin/map/ipv6':
            return self.redirect('/admin/map/ipv6/all')

        parts = self.request.path.strip('/').split('/')

        # http://mlab-ns.appspot.com/admin/map/ipv4/[ndt|npad|neubot|glasnost]
        # http://mlab-ns.appspot.com/admin/map/ipv6/[ndt|npad|neubot|glasnost]
        if 'map' in parts:
            tool_id = parts[len(parts) - 1]
            address_family = 'ipv4'
            if 'ipv6' in parts:
                address_family = 'ipv6'
            return self.map_view(tool_id, address_family)

        return self.redirect('/admin/map/ipv4/all')

    def sliver_tool_view(self):
        """Returns an HTML page containing sliver tools information."""
        headers = [
            'Tool',
            'Site',
            'Slice',
            'Server',
            'Status IPv4',
            'Status IPv6',
            'Sliver IPv4',
            'Sliver IPv6',
            'When']

        sliver_tools = model.SliverTool.gql('ORDER BY tool_id DESC')
        records = []
        for sliver_tool in sliver_tools:
            sliver_tool_info = [
                sliver_tool.tool_id,
                sliver_tool.site_id,
                sliver_tool.slice_id,
                sliver_tool.server_id,
                sliver_tool.status_ipv4,
                sliver_tool.status_ipv6,
                sliver_tool.sliver_ipv4,
                sliver_tool.sliver_ipv6,
                sliver_tool.when ]
            records.append(sliver_tool_info)

        values = {'records' : records, 'headers': headers}
        self.response.out.write(
            template.render('mlabns/templates/sliver_tool.html', values))

    def site_view(self):
        """Returns an HTML page containing sites information."""
        headers = [
            'Site ID',
            'City',
            'Country',
            'Latitude',
            'Longitude',
            'Metro',
            'When']

        sites = model.Site.gql('ORDER BY site_id DESC')
        records = []
        for site in sites:
            site_info = [
                site.site_id,
                site.city,
                site.country,
                site.latitude,
                site.longitude,
                site.metro,
                site.when ]
            records.append(site_info)

        values = {'records' : records, 'headers': headers}
        self.response.out.write(
            template.render('mlabns/templates/site.html', values))

    def map_view(self, tool_id, address_family):
        """Displays a per tool map with the status of the slivers.

        Args:
            tool_id: A string representing the tool id(e.g., npad, ndt).
            address_family: A string specifying the address family(ipv4,ipv6).

        """
        sliver_tools = None

        if tool_id == 'all':
            sliver_tools = model.SliverTool.gql('ORDER BY tool_id DESC')
        else:
            cached_sliver_tools = memcache.get(tool_id)
            if cached_sliver_tools:
                sliver_tools = cached_sliver_tools.values()
            else:
                sliver_tools = model.SliverTool.gql(
                    'WHERE tool_id=:tool_id '
                    'ORDER BY tool_id DESC',
                    tool_id=tool_id)

        if not sliver_tools:
            return util.send_not_found(self)

        data = self.get_sites_info(sliver_tools, address_family)
        json_data = simplejson.dumps(data)
        file_name = '' . join([
            'mlabns/templates/',tool_id,'_map_view_',address_family,'.html'])
        self.response.out.write(
            template.render(file_name, {'cities' : json_data}))

    def get_sites_info(self, sliver_tools, address_family):
       """Returns info about the sites.

        This data is used to build the markers on the map. In particular,
        there is a marker for each city and an info window that pops up
        when clicking on a marker showing information about the sites.

        Args:
            sliver_tools: A list of sliver_tools.
            address_family: A string specifying the address family(ipv4,ipv6).

        Returns:
            A dict of the form (key=city, value=[site_info, site_info, ...],
            containing for each city the list of the sites deployed in
            that particular city. Each 'site_info' element is a dict
            containing all relevant information about the site:
            (e.g., site_id, city, country, latitude, longitude,..) plus
            a list of sliver_tool_info elements with information and status
            of the slivers. Each sliver_tool _info contains: slice_id,
            tool_id, server_id, status (status_ipv4 or status_ipv6, depending
            on the 'address_family' argument) and timestamp of the last
            update.

        """

        sites = model.Site.gql('ORDER BY site_id DESC')
        site_dict = {}
        sites_per_city = {}
        for site in sites:
            site_info = {}
            site_info['site_id'] = site.site_id
            site_info['city'] = site.city
            site_info['country'] = site.country
            site_info['latitude'] = site.latitude
            site_info['longitude'] = site.longitude
            site_info['sliver_tools'] = []
            site_dict[site.site_id] = site_info
            sites_per_city[site.city] = []

        # Add sliver tools info to the sites.
        for sliver_tool in sliver_tools:
            sliver_tool_info = {}
            sliver_tool_info['slice_id'] = sliver_tool.slice_id
            sliver_tool_info['tool_id'] = sliver_tool.tool_id
            sliver_tool_info['server_id'] = sliver_tool.server_id
            if address_family == 'ipv4':
                sliver_tool_info['status'] = sliver_tool.status_ipv4
            else:
                sliver_tool_info['status'] = sliver_tool.status_ipv6

            sliver_tool_info['timestamp'] = sliver_tool.when.strftime(
                '%Y-%m-%d %H:%M:%S')
            site_dict[sliver_tool.site_id]['sliver_tools'].append(
                sliver_tool_info)

        for item in site_dict:
            city = site_dict[item]['city']
            sites_per_city[city].append(site_dict[item])

        return sites_per_city

