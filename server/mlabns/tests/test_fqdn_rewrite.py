import mock
import unittest

from mlabns.util import fqdn_rewrite
from mlabns.util import message


class FqdnRewriteTest(unittest.TestCase):

    def setUp(self):
        # Initialize the SITE_REGEX  and MACHINE_REGEX env variable.
        environ_patch = mock.patch.dict('os.environ', {
            'MACHINE_REGEX': '^mlab4$',
            'SITE_REGEX': '^[a-z]{3}[0-9c]{2}$',
        })
        self.addCleanup(environ_patch.stop)
        environ_patch.start()

    def testAfAgnosticNdtFqdn(self):
        """When there is no AF and tool is not NDT-SSL, don't rewrite."""
        fqdn = 'ndt-iupui-mlab4-lga06.mlab-staging.measurement-lab.org'
        self.assertEqual(fqdn, fqdn_rewrite.rewrite(fqdn, None, 'ndt'))

    def testIPv4NdtFqdn(self):
        """Add a v4 annotation for v4-specific requests."""
        fqdn_original = 'ndt-iupui-mlab4-lga06.mlab-staging.measurement-lab.org'
        fqdn_expected = 'ndt-iupui-mlab4v4-lga06.mlab-staging.measurement-lab.org'
        fqdn_actual = fqdn_rewrite.rewrite(fqdn_original,
                                           message.ADDRESS_FAMILY_IPv4, 'ndt')
        self.assertEqual(fqdn_expected, fqdn_actual)

    def testIPv4WeheFqdn(self):
        """Add a v4 annotation for v4-specific requests."""
        fqdn_original = 'wehe-mlab4-lga06.mlab-staging.measurement-lab.org'
        fqdn_expected = 'wehe-mlab4v4-lga06.mlab-staging.measurement-lab.org'
        fqdn_actual = fqdn_rewrite.rewrite(fqdn_original,
                                           message.ADDRESS_FAMILY_IPv4, 'ndt')
        self.assertEqual(fqdn_expected, fqdn_actual)

    def testIPv6NdtFqdn(self):
        """Add a v6 annotation for v6-specific requests."""
        fqdn_original = 'ndt-iupui-mlab4-lga06.mlab-staging.measurement-lab.org'
        fqdn_expected = 'ndt-iupui-mlab4v6-lga06.mlab-staging.measurement-lab.org'
        fqdn_actual = fqdn_rewrite.rewrite(fqdn_original,
                                           message.ADDRESS_FAMILY_IPv6, 'ndt')
        self.assertEqual(fqdn_expected, fqdn_actual)

    def testIPv4WeheFqdnFlat(self):
        """Add a v4 annotation for v4-specific requests."""
        fqdn_original = 'wehe-mlab4-lga0t.mlab-sandbox.measurement-lab.org'
        fqdn_expected = 'wehe-mlab4v4-lga0t.mlab-sandbox.measurement-lab.org'
        fqdn_actual = fqdn_rewrite.rewrite(fqdn_original,
                                           message.ADDRESS_FAMILY_IPv4, 'ndt')
        self.assertEqual(fqdn_expected, fqdn_actual)


if __name__ == '__main__':
    unittest.main()
