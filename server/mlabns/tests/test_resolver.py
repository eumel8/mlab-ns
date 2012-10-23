import unittest
import unittest2

from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import testbed

from mlabns.util import constants
from mlabns.util import message
from mlabns.util import resolver


# Defined at top level, to avoid pickle error, when using memcache.
class SliverToolMockup:
    def __init__(self, status_ipv4, status_ipv6):
        self.status_ipv4 = status_ipv4
        self.status_ipv6 = status_ipv6


class ResolverBaseTestCase(unittest2.TestCase):
    def testGetCandidates(self):
        
        class QueryMockup:
            pass
            
        class ResolverBaseMockup(resolver.ResolverBase):
            def _get_candidates(self, unused_arg, address_family):
                if address_family == message.ADDRESS_FAMILY_IPv6:
                    return ['valid_candidate']
                return []

        base_resolver = ResolverBaseMockup()
        
        # Case 1) List is not empty for the input address family.
        query = QueryMockup()
        query.address_family = message.ADDRESS_FAMILY_IPv6
        self.assertListEqual(['valid_candidate'],
                             base_resolver.get_candidates(query))
        
        # Case 2) List is empty for input address_family and there is no
        #         user-defined address family.
        query = QueryMockup()
        query.address_family = message.ADDRESS_FAMILY_IPv4
        query.user_defined_af = None        
        self.assertListEqual(['valid_candidate'],
                             base_resolver.get_candidates(query))
                
        # Case 3) List is empty for input address_family and user-defined
        #         address family == input address family.
        query = QueryMockup()
        query.address_family = message.ADDRESS_FAMILY_IPv4
        query.user_defined_af = message.ADDRESS_FAMILY_IPv4
        self.assertEqual(len(base_resolver.get_candidates(query)), 0)
        
        # Case 4) List is empty for input address_family and user-defined
        #         address family != input address family.
        query = QueryMockup()
        query.address_family = message.ADDRESS_FAMILY_IPv4
        query.user_defined_af = message.ADDRESS_FAMILY_IPv6
        self.assertListEqual(['valid_candidate'],
                             base_resolver.get_candidates(query))

    def testGetCandidatesYesMemcache(self):
                
        # Set up memcache stub.
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_memcache_stub()
        sliver_tool_list = [
            SliverToolMockup(message.STATUS_ONLINE, message.STATUS_OFFLINE),
            SliverToolMockup(message.STATUS_OFFLINE, message.STATUS_ONLINE),
            SliverToolMockup(message.STATUS_OFFLINE, message.STATUS_ONLINE),
            SliverToolMockup(message.STATUS_ONLINE, message.STATUS_ONLINE),
            SliverToolMockup(message.STATUS_OFFLINE, message.STATUS_OFFLINE)]
        memcache.set('valid_tool_id', sliver_tool_list,
                     namespace=constants.MEMCACHE_NAMESPACE_TOOLS)
            
        class QueryMockup:
            def __init__(self):
                self.tool_id = 'valid_tool_id'
            
        base_resolver = resolver.ResolverBase()
        self.assertEqual(
            2, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv4)))
        self.assertEqual(
            3, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv6)))
                
        # Tear down stub.
        self.testbed.deactivate()

    def testGetCandidatesYesMemcacheButOffline(self):

        class QueryMockup:
            def __init__(self):
                self.tool_id = 'valid_tool_id'
    
        class SliverTool(db.Model):
            tool_id = db.StringProperty()
            status_ipv4 = db.StringProperty()
            status_ipv6 = db.StringProperty()

        class TestEntityGroupRoot(db.Model):
            """Entity group root"""
            pass
               
        # Set up datastore and memcache stubs.
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()
        
        sliver_tool_list = [
            SliverToolMockup(message.STATUS_OFFLINE, message.STATUS_OFFLINE)]
        memcache.set('valid_tool_id', sliver_tool_list,
                     namespace=constants.MEMCACHE_NAMESPACE_TOOLS)

        root = TestEntityGroupRoot(key_name='root')
        st1 = SliverTool(parent=root.key())
        st1.tool_id = 'valid_tool_id'
        st1.status_ipv4 = message.STATUS_ONLINE
        st1.status_ipv6 = message.STATUS_ONLINE
        st1.put()
                        
        base_resolver = resolver.ResolverBase()
        self.assertEqual(
            0, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv4)))
        self.assertEqual(
            0, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv6)))
                
        # Tear down stub.
        self.testbed.deactivate()

    def testGetCandidatesNoMemcacheYesDatastore(self):

        class QueryMockup:
            def __init__(self):
                self.tool_id = 'valid_tool_id'
    
        class SliverTool(db.Model):
            tool_id = db.StringProperty()
            status_ipv4 = db.StringProperty()
            status_ipv6 = db.StringProperty()

        class TestEntityGroupRoot(db.Model):
            """Entity group root"""
            pass
               
        # Set up datastore and memcache stubs.
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()
        
        root = TestEntityGroupRoot(key_name='root')
        st1 = SliverTool(parent=root.key())
        st1.tool_id = 'valid_tool_id'
        st1.status_ipv4 = message.STATUS_ONLINE
        st1.status_ipv6 = message.STATUS_ONLINE
        st1.put()
        st2 = SliverTool(parent=root.key())
        st2.tool_id = 'valid_tool_id'
        st2.status_ipv4 = message.STATUS_ONLINE
        st2.status_ipv6 = message.STATUS_OFFLINE
        st2.put()
        st3 = SliverTool(parent=root.key())
        st3.tool_id = 'valid_tool_id'
        st3.status_ipv4 = message.STATUS_OFFLINE
        st3.status_ipv6 = message.STATUS_ONLINE
        st3.put()
        st4 = SliverTool(parent=root.key())
        st4.tool_id = 'valid_tool_id'
        st4.status_ipv4 = message.STATUS_OFFLINE
        st4.status_ipv6 = message.STATUS_ONLINE
        st4.put()
        st5 = SliverTool(parent=root.key())
        st5.tool_id = 'valid_tool_id'
        st5.status_ipv4 = message.STATUS_OFFLINE
        st5.status_ipv6 = message.STATUS_OFFLINE
        st5.put()
                        
        base_resolver = resolver.ResolverBase()
        self.assertEqual(
            2, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv4)))
        self.assertEqual(
            3, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv6)))
                
        # Tear down stub.
        self.testbed.deactivate()

    def testGetCandidatesNoMemcacheNoDatastore(self):

        class QueryMockup:
            def __init__(self):
                self.tool_id = 'valid_tool_id'
    
        class SliverTool(db.Model):
            tool_id = db.StringProperty()
            status_ipv4 = db.StringProperty()
            status_ipv6 = db.StringProperty()

        class TestEntityGroupRoot(db.Model):
            """Entity group root"""
            pass
               
        # Set up datastore and memcache stubs.
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()
        
        sliver_tool_list = [
            SliverToolMockup(message.STATUS_OFFLINE, message.STATUS_OFFLINE)]
        memcache.set('valid_tool_id', sliver_tool_list,
                     namespace=constants.MEMCACHE_NAMESPACE_TOOLS)

        root = TestEntityGroupRoot(key_name='root')
        st1 = SliverTool(parent=root.key())
        st1.tool_id = 'valid_tool_id'
        st1.status_ipv4 = message.STATUS_OFFLINE
        st1.status_ipv6 = message.STATUS_OFFLINE
        st1.put()
                        
        base_resolver = resolver.ResolverBase()
        self.assertEqual(
            0, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv4)))
        self.assertEqual(
            0, len(base_resolver._get_candidates(QueryMockup(), 
                                                 message.ADDRESS_FAMILY_IPv6)))
                
        # Tear down stub.
        self.testbed.deactivate()
                
    def testAnswerQueryEmptyResult(self):
        class QueryMockup:
            def __init__(self):
                self.tool_id = 'tool_id'
            
        class ResolverBaseMockup(resolver.ResolverBase):
            def get_candidates(self, unused_arg):
                return []
        
        base_resolver = ResolverBaseMockup()
        query = QueryMockup()
        self.assertIsNone(base_resolver.answer_query(query))
        
    def testAnswerQueryNonEmptyResult(self):
        class QueryMockup:
            def __init__(self):
                self.tool_id = 'tool_id'
            
        class ResolverBaseMockup(resolver.ResolverBase):
            def get_candidates(self, unused_arg):
                return ['valid_candidate']
        
        base_resolver = ResolverBaseMockup()
        query = QueryMockup()
        self.assertListEqual(['valid_candidate'],
                             base_resolver.get_candidates(query))


class GeoResolverTestCase(unittest2.TestCase):
    def testAnswerQueryNoCandidates(self):
        
        class QueryMockup:
            def __init__(self):
                self.tool_id = 'valid_tool_id'
            
        class GeoResolverMockup(resolver.GeoResolver):
            def get_candidates(self, unused_arg):
                return []

        geo_resolver = GeoResolverMockup()
        self.assertIsNone(geo_resolver.answer_query(QueryMockup()))

    def testAnswerQueryNoLatLon(self): 
       
        class QueryMockup:
            def __init__(self):
                self.latitude = None
                self.longitude = None
             
        class GeoResolverMockup(resolver.GeoResolver):
            def get_candidates(self, unused_arg):
                return ['valid_candidate']

        geo_resolver = GeoResolverMockup()
        self.assertEqual('valid_candidate',
                         geo_resolver.answer_query(QueryMockup()))

    def testAnswerQueryAllCandidatesSameSite(self): 
       
        class QueryMockup:
            def __init__(self):
                self.latitude = 0.0
                self.longitude = 0.0
             
        class SliverToolMockup:
            def __init__(self):
                self.site_id = 'valid_site_id'
                self.latitude = 2.0
                self.longitude = 1.0
                
        class GeoResolverMockup(resolver.GeoResolver):
            def get_candidates(self, unused_arg):
                return [SliverToolMockup(), SliverToolMockup()]
                        
        geo_resolver = GeoResolverMockup()
        result = geo_resolver.answer_query(QueryMockup())
        self.assertEqual(2.0, result.latitude)
        self.assertEqual(1.0, result.longitude)

    def testAnswerQueryAllCandidatesDifferentSitesOneClosest(self): 
       
        class QueryMockup:
            def __init__(self):
                self.latitude = 0.0
                self.longitude = 0.0
             
        class SliverToolMockup:
            def __init__(self, site, lat, lon):
                self.site_id = site
                self.latitude = lat
                self.longitude = lon
                
        class GeoResolverMockup(resolver.GeoResolver):
            def get_candidates(self, unused_arg):
                return [SliverToolMockup('a', 2.0, 1.0),
                        SliverToolMockup('b', 20.0, 34.9)]
                        
        geo_resolver = GeoResolverMockup()
        result = geo_resolver.answer_query(QueryMockup())
        self.assertEqual(2.0, result.latitude)
        self.assertEqual(1.0, result.longitude)

    def testAnswerQueryAllCandidatesDifferentSitesMultipleClosest(self): 
       
        class QueryMockup:
            def __init__(self):
                self.latitude = 0.0
                self.longitude = 0.0
             
        class SliverToolMockup:
            def __init__(self, site, lat, lon):
                self.site_id = site
                self.latitude = lat
                self.longitude = lon
                
        class GeoResolverMockup(resolver.GeoResolver):
            def get_candidates(self, unused_arg):
                return [SliverToolMockup('a', 2.0, 1.0),
                        SliverToolMockup('b', 20.0, 34.9),
                        SliverToolMockup('c', 2.0, 1.0)]
                        
        geo_resolver = GeoResolverMockup()
        result = geo_resolver.answer_query(QueryMockup())
        self.assertEqual(2.0, result.latitude)
        self.assertEqual(1.0, result.longitude)


class CountryResolverTestCase(unittest2.TestCase):
    def testAnswerQueryNoUserDefinedCountry(self):
        
        class QueryMockup:
            def __init__(self):
                self.user_defined_country = None
            
        class CountryResolverMockup(resolver.CountryResolver):
            pass

        country_resolver = CountryResolverMockup()
        self.assertIsNone(country_resolver.answer_query(QueryMockup()))
        
    def testAnswerQueryNoCandidates(self):
        
        class QueryMockup:
            def __init__(self):
                self.user_defined_country = 'valid_country'
                self.tool_id = 'valid_tool_id'
            
        class CountryResolverMockup(resolver.CountryResolver):
            def get_candidates(self, unused_arg):
                return []

        country_resolver = CountryResolverMockup()
        self.assertIsNone(country_resolver.answer_query(QueryMockup()))

    def testAnswerQueryNoCandidatesInUserDefinedCountry(self): 
       
        class QueryMockup:
            def __init__(self):
                self.user_defined_country = 'valid_country'
                self.tool_id = 'valid_tool_id'
            
        class SliverToolMockup:
            def __init__(self, country):
                self.country = country
                
        class CountryResolverMockup(resolver.CountryResolver):
            def get_candidates(self, unused_arg):
                return [SliverToolMockup('valid_country1'),
                        SliverToolMockup('valid_country2')]

        country_resolver = CountryResolverMockup()
        self.assertIsNone(country_resolver.answer_query(QueryMockup()))

    def testAnswerQueryCandidatesInUserDefinedCountry(self): 
       
        class QueryMockup:
            def __init__(self):
                self.user_defined_country = 'valid_country'
                self.tool_id = 'valid_tool_id'
            
        class SliverToolMockup:
            def __init__(self, country):
                self.country = country
                
        class CountryResolverMockup(resolver.CountryResolver):
            def get_candidates(self, unused_arg):
                return [SliverToolMockup('valid_country'),
                        SliverToolMockup('valid_country2')]

        country_resolver = CountryResolverMockup()
        result = country_resolver.answer_query(QueryMockup())
        self.assertEqual('valid_country', result.country)
        
        
class ResolverTestCase(unittest2.TestCase):
    def testNewResolver(self):
        self.assertIsInstance(resolver.new_resolver(message.POLICY_GEO),
                              resolver.GeoResolver)
        self.assertIsInstance(resolver.new_resolver(message.POLICY_METRO),
                              resolver.MetroResolver)
        self.assertIsInstance(resolver.new_resolver(message.POLICY_RANDOM),
                              resolver.RandomResolver)
        self.assertIsInstance(resolver.new_resolver(message.POLICY_COUNTRY),
                              resolver.CountryResolver)
        self.assertIsInstance(resolver.new_resolver('another_policy'),
                              resolver.RandomResolver)


if __name__ == '__main__':
    unittest2.main()
