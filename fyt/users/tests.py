
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings
from django.core.urlresolvers import reverse
from model_mommy import mommy

from fyt.users.models import DartmouthUser
from fyt.test.testcases import WebTestCase


def lookup_email(*args, **kwargs):
    return 'email'


class UserManagerTestCase(TestCase):

    @patch('fyt.users.models.lookup_email', new=lookup_email)
    def test_create_user_without_did(self):

        netid = 'd123456z'
        name = 'Igor'

        user, ct = DartmouthUser.objects.get_or_create_by_netid(netid, name)
        self.assertTrue(ct)
        self.assertEqual(user.netid, netid)
        self.assertEqual(user.name, name)
        self.assertEqual(user.did, '')

    @patch('fyt.users.models.lookup_email', new=lookup_email)
    def test_create_user_then_add_did(self):

        netid = 'd123456z'
        name = 'Igor'
        user, ct = DartmouthUser.objects.get_or_create_by_netid(netid, name)

        DID = 'destiny'
        user, ct = DartmouthUser.objects.get_or_create_by_netid(netid, name, did=DID)
        self.assertFalse(ct)
        self.assertEqual(user.netid, netid)
        self.assertEqual(user.name, name)
        self.assertEqual(user.did, DID)

    def test_email_lookup_error_sets_blank_email(self):
        user = DartmouthUser.objects.create_user('junk_netid', 'name')
        self.assertEqual(user.email, '')


class NetIdFieldTestCase(TestCase):

    def test_lowercase_conversion(self):
        netid = 'D34898Z'
        user = mommy.make(DartmouthUser, netid=netid)
        self.assertEqual(user.netid, netid.lower())

    def test_lowercase_conversion_and_query(self):
        netid = 'D34898Z'
        user = mommy.make(DartmouthUser, netid=netid)
        self.assertEqual(user, DartmouthUser.objects.get(netid=netid))


class UserEmailMiddlewareTestCase(WebTestCase):

    def test_user_with_no_email_must_manually_add_email(self):
        user = DartmouthUser.objects.create(
            netid='d34898z', name='test', email='')
        resp = self.app.get('/', user=user, status=302).follow()
        self.assertEqual(resp.request.path, reverse('users:update_email'))
        resp.form['email'] = 'd34898z@test.com'
        resp = resp.form.submit().follow()
        # redirects back to original location
        self.assertEqual(resp.request.path, '/')
        # and updates email
        user = DartmouthUser.objects.get(pk=user.pk)
        self.assertEqual(user.email, 'd34898z@test.com')

    @override_settings(CAS_LOGOUT_COMPLETELY=False)
    def test_do_not_ask_for_email_when_logging_out(self):
        user = DartmouthUser.objects.create(
            netid='d34898z', name='test', email='')
        resp = self.app.get(reverse('users:logout'), user=user).follow()
        self.assertFalse(resp.request.path.startswith(reverse('users:update_email')))