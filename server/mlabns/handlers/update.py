from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

import json
import logging
import time
import urllib2

from mlabns.db import model
from mlabns.util import constants
from mlabns.util import message
from mlabns.util import util


class SiteRegistrationHandler(webapp.RequestHandler):
    """Registers new sites from ks."""

    class SiteRegistrationMessage:
        # Message fields
        SITE_FIELD = 'site'
        METRO_FIELD = 'metro'
        CITY_FIELD = 'city'
        COUNTRY_FIELD = 'country'
        LAT_FIELD = 'latitude'
        LON_FIELD = 'longitude'
        REQUIRED_FIELDS = [ SITE_FIELD, METRO_FIELD, CITY_FIELD, COUNTRY_FIELD,
                            LAT_FIELD, LON_FIELD]

        def validate_site_json(self, site_json):
           """Checks if the json data from ks is well formed.

            Args:
                site_json: A json representing the site info as appears on ks.

            Returns:
                True if the json data is valid, False otherwise.
            """
            # TODO(claudiu) Need more robust validation.
            for field in SiteRegistrationMessage.REQUIRED_FIELDS:
                if field not in site_json:
                    logging.error('Missing field from site list: %s.', field)
                    return False
            return True

    SITE_LIST_URL = 'http://ks.measurementlab.net/mlab-site-stats.json'

    def get(self):
        """Triggers the registration handler.

        Checks if new sites were added to ks and registers them with mlab-ns.
        """
        try:
            ks_sites_json = json.loads(urllib2.urlopen(SITE_LIST_URL).read())
        except urllib2.HTTPError:
            # TODO(claudiu) Notify(email) when this happens.
            logging.error('Cannot connect to ks.')
            return util.send_not_found(self)
        except (TypeError, ValueError) as e:
            logging.error('Invalid json format from ks.')
            return util.send_not_found(self)

        ks_site_ids = set()

        # Validate the data from ks.
        valid_ks_sites_json = []
        for ks_site in ks_sites_json:
            if self.validate_site_json(ks_site):
                valid_ks_sites_json.append(ks_site)
                ks_site_ids.add(ks_site[SiteRegistrationMessage.SITE_FIELD])
            else:
               logging.error('Invalid json format from ks.')
               continue

        mlab_site_ids = set()
        mlab_sites = model.Site.all()
        for site in mlab_sites:
            mlab_site_ids.add(site.site_id)

        unchanged_site_ids = ks_site_ids.intersection(mlab_site_ids)
        new_site_ids = ks_site_ids.difference(mlab_site_ids)
        removed_site_ids = mlab_site_ids.difference(ks_site_ids)

        # Register only new sites.
        # Do not remove sites here for now.
        # TODO(claudiu) Implement the site removal as a separate handler.
        for site_id in removed_site_ids:
            logging.warning('Site removed from ks: %s.', site_id)

        for site_id in unchanged_site_ids:
            logging.info('Unchanged site: %s.', site_id)

        for ks_site in valid_ks_sites_json:
            if (ks_site[SiteRegistrationMessage.SITE_FIELD] in new_site_ids):
                logging.info('Registering site: %s.',
                             ks_site[SiteRegistrationMessage.SITE_FIELD])
                # TODO(claudiu) Notify(email) when this happens.
                if not SiteRegistrationMessage.register_site(ks_site):
                    logging.error('Error registering site %s.',
                                  ks_site[SiteRegistrationMessage.SITE_FIELD])
                    return util.send_not_found(self)

        return util.send_success(self)


    def register_site(self, ks_site):
        """Registers a new site.

        Args:
            ks_site: A json representing the site info as appears on ks.

        Returns:
            True if the registration succeeds, False otherwise.
        """
        try:
            lat_long = float(ks_site[SiteRegistrationMessage.LAT_FIELD])
            lon_long = float(ks_site[SiteRegistrationMessage.LON_FIELD])
        except ValueError:
            logging.error('Geo coordinates are not float (%s, %s)',
                           ks_site[SiteRegistrationMessage.LAT_FIELD],
                           ks_site[SiteRegistrationMessage.LON_FIELD])
            return False
        site = model.Site(
            site_id = ks_site[SiteRegistrationMessage.SITE_FIELD],
            city = ks_site[SiteRegistrationMessage.CITY_FIELD],
            country = ks_site[SiteRegistrationMessage.COUNTRY_FIELD],
            latitude = lat_long,
            longitude = lon_long,
            metro = ks_site[SiteRegistrationMessage.METRO_FIELD],
            registration_timestamp=long(time.time()),
            key_name=ks_site[SiteRegistrationMessage.SITE_FIELD])

        try:
            site.put()
        except TransactionFailedError:
            # TODO(claudiu) Trigger an event/notification.
            logging.error('Failed to write changes to db.')
            return False

        sliver_tools = []
        tools = model.Tool.all()
        for tool in tools:
            for server_id in ['mlab1', 'mlab2', 'mlab3']:
                sliver_tool_id = model.get_sliver_tool_id(
                    tool.tool_id,
                    tool.slice_id,
                    server_id,
                    ks_site[SiteRegistrationMessage.SITE_FIELD])

                fqdn = model.get_fqdn(
                    tool.slice_id, server_id,
                    ks_site[SiteRegistrationMessage.SITE_FIELD])
                if fqdn is None:
                    logging.error('Non valid slice id: %s.', tool.slice_id)
                    continue
                sliver_tool = model.SliverTool(
                    tool_id = tool.tool_id,
                    slice_id = tool.slice_id,
                    site_id = ks_site[SiteRegistrationMessage.SITE_FIELD],
                    server_id = server_id,
                    fqdn = fqdn,
                    # server_port is currently unused.
                    server_port = None,
                    http_port = tool.http_port,
                    # IP addresses will be updated by the IPUpdateHandler.
                    sliver_ipv4 = message.NO_IP_ADDRESS,
                    sliver_ipv6 = message.NO_IP_ADDRESS,
                    # Status will be updated by the StatusUpdateHandler.
                    status_ipv4 = message.STATUS_OFFLINE,
                    status_ipv6 = message.STATUS_OFFLINE,
                    latitude = site.latitude,
                    longitude = site.longitude,
                    city = site.city,
                    country = site.country,
                    update_request_timestamp = long(time.time()),
                    key_name=sliver_tool_id)

                sliver_tools.append(sliver_tool)

        # Insert all new sliver_tools in the datastore
        # in one batch operation.
        try:
            db.put(sliver_tools)
        except TransactionFailedError:
            # TODO(claudiu) Trigger an event/notification.
            logging.error('Failed to write changes to db.')
            return False

        return True

class IPUpdateHandler(webapp.RequestHandler):
    """ Updates SliverTools' IP addresses from ks."""

    IP_LIST_URL = 'http://ks.measurementlab.net/mlab-host-ips.txt'

    def get(self):
        """Triggers the update handler.

        Updates sliver tool IP addresses from ks.
        """
        ip = {}
        lines = []
        try:
            lines = urllib2.urlopen(IP_LIST_URL).read().strip('\n').split('\n')
        except urllib2.HTTPError:
            # TODO(claudiu) Notify(email) when this happens.
            logging.error('Cannot connect to ks.')
            return util.send_not_found(self)

        sliver_tool_list = {}
        for line in lines:
            # Expected format: "FQDN,IPv4,IPv6" (IPv6 can be an empty string).
            line_fields = line.split(',')
            if len(line_fields) != 2:
                logging.error('Malformed line: %s.', line)
                continue
            fqdn = line_fields[0]
            ipv4 = line_fields[1]
            ipv6 = line_fields[2]
            logging.info('Updating %s.', fqdn)

            sliver_tool_gql = model.SliverTool.gql('WHERE fqdn=:fqdn',
                                                   fqdn=fqdn)
            # FQDN is unique so get() should be enough.
            sliver_tool = sliver_tool_gql.get()

            if sliver_tool == None:
                logging.warning('Unable to find sliver_tool with fqdn %s', fqdn)
                continue;

            sliver_tool.sliver_ipv4 = message.NO_IP_ADDRESS
            if ipv4 != None:
                sliver_tool.sliver_ipv4 = ipv4
            sliver_tool.sliver_ipv6 = message.NO_IP_ADDRESS
            if ipv6 != None:
                sliver_tool.sliver_ipv6 = ipv6

            try:
                sliver_tool.put()
                logging.info('Updated %s to IPv4 %s, IPv6 %s', fqdn, ipv4, ipv6)
            except db.TransactionFailedError:
                logging.error('Failed to write changes to db')
                continue

            if sliver_tool.tool_id not in sliver_tool_list:
                sliver_tool_list[sliver_tool.tool_id] = []
                sliver_tool_list[sliver_tool.tool_id].append(sliver_tool)

        # Update memcache
        for tool_id in sliver_tool_list.keys():
           if not memcache.set(tool_id, sliver_tool_list[tool_id],
                              namespace=constants.MEMCACHE_NAMESPACE_TOOLS):
              logging.error('Memcache set failed')


class StatusUpdateHandler(webapp.RequestHandler):
    """Updates SliverTools' status from nagios."""

    AF_IPV4 = ''
    AF_IPV6 = '_ipv6'
    NAGIOS_AF_SUFFIXES = [ AF_IPV4, AF_IPV6 ]

    def get(self):
        """Triggers the update handler.

        Updates sliver status with information from nagios. The nagios url
        containing the information is stored in the Nagios db along with
        the credentials necessary to access the data.
        """
        nagios = model.Nagios.get_by_key_name(
            constants.DEFAULT_NAGIOS_ENTRY)

        password_manager = urllib2.HTTPPasswordMgrWithDefaultRealm()
        password_manager.add_password(
            None, nagios.url, nagios.username, nagios.password)

        authhandler = urllib2.HTTPDigestAuthHandler(password_manager)
        opener = urllib2.build_opener(authhandler)
        urllib2.install_opener(opener)

        slices_gql = model.Tool.gql('ORDER by tool_id DESC')
        for item in slices_gql.run(batch_size=constants.GQL_BATCH_SIZE):
            logging.info('Tool is %s', item.tool_id)
            for family in NAGIOS_AF_SUFFIXES:
              slice_url = nagios.url + '?show_state=1&service_name=' + \
                    item.tool_id + family

              slice_status = self.get_slice_status(slice_url)
              self.update_sliver_tools_status(slice_status, item.tool_id,
                                              family)

    def update_sliver_tools_status(self, slice_status, tool_id, family):
        """Updates sliver tools status.

        Args:
            slice_status: A dict that contains the status of the
                slivers in the slice {key=fqdn, status:online|offline}
            tool_id: A string representing the fqdn that resolves
                to an IP address.
        """

        sliver_tools_gql = model.SliverTool.gql('WHERE tool_id=:tool_id',
                                                tool_id=tool_id)
        sliver_tool_list = []
        for sliver_tool in sliver_tools_gql.run(
            batch_size=constants.GQL_BATCH_SIZE):
            if sliver_tool.fqdn not in slice_status:
                # No updates for this sliver.
                continue

            if family == AF_IPV4:
                if sliver_tool.sliver_ipv4 == message.NO_IP_ADDRESS:
                    logging.warning('Setting IPv4 status of %s to offline due '\
                                    'to missing IP.', sliver_fqdn)
                    slice_status[sliver_fqdn] = message.STATUS_OFFLINE
                    sliver_tool.status_ipv4 = slice_status[sliver_fqdn]
            elif family == AF_IPV6:
                if sliver_tool.sliver_ipv6 == message.NO_IP_ADDRESS:
                    logging.warning('Setting IPv6 status for %s to offline ' \
                                    'due to missing IP.', sliver_fqdn)
                    slice_status[sliver_fqdn] = message.STATUS_OFFLINE
                    sliver_tool.status_ipv6 = slice_status[sliver_fqdn]
             else:
                 logging.error('Unexpected family: %s', family)
                 continue

             sliver_tool.update_request_timestamp = long(time.time())
             # Write changes to db.
             try:
                 sliver_tool.put()
                 logging.info('Updating %s: status is %s.',
                              sliver_fqdn, slice_status[sliver_fqdn])
             except TransactionFailedError:
                 # TODO(claudiu) Trigger an event/notification.
                 logging.error('Failed to write changes to db.')
                 continue
             sliver_tool_list.append(sliver_tool)

        # Never set the memcache to an empty list since it's more likely that
        # this is a Nagios failure.
        if sliver_tool_list:
            if not memcache.set(tool_id, sliver_tool_list,
                                namespace=constants.MEMCACHE_NAMESPACE_TOOLS):
                logging.error('Memcache set failed')

    def get_slice_status(self, url):
        """Read slice status from Nagios.

        Args:
            url: String representing the URL to Nagios for a single slice.

        Returns:
            A dict that contains the status of the slivers in this
            slice {key=fqdn, status:online|offline}
        """
        status = {}
        try:
            lines = urllib2.urlopen(url).read().strip('\n').split('\n')
            for line in lines:
                if len(line) == 0:
                    continue
                # See the design doc for a description of the file format.
                slice_fqdn, state, state_type = line.split(' ')
                sliver_fqdn, tool_id = slice_fqdn.split('/')
                status[sliver_fqdn] = message.STATUS_ONLINE
                if state != constants.NAGIOS_SERVICE_STATUS_OK:
                    status[sliver_fqdn] = message.STATUS_OFFLINE
        except urllib2.HTTPError:
            # TODO(claudiu) Notify(email) when this happens.
            logging.error('Cannot connect to nagios monitoring system.')

        return status
