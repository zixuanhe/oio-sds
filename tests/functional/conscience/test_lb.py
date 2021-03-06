"""Test the load balancer through the proxy"""

import time
from tests.utils import BaseTestCase
from tests.utils import CODE_SRVTYPE_NOTMANAGED, CODE_POLICY_NOT_SATISFIABLE


class BaseLbTest(BaseTestCase):

    def fill_slots(self, slots, count=1, lowport=7000):
        for num in range(count):
            srvin = self._srv('echo',
                              extra_tags={"tag.slots": ','.join(slots)},
                              lowport=lowport,
                              highport=lowport+100)
            self._lock_srv(srvin)

    def fill_sameport(self, count=1):
        for num in range(count):
            srvin = self._srv('echo', lowport=7000, highport=7000,
                              ip='127.0.0.%d' % (2+num))
            self._lock_srv(srvin)


class TestLbChoose(BaseLbTest):

    def test_choose_1(self):
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'rawx'})
        self.assertEqual(resp.status_code, 200)
        parsed = resp.json()
        self.assertIsInstance(parsed, list)
        self.assertIsInstance(parsed[0], dict)
        resp = self.session.get(self._url_lb('nothing'),
                                params={'type': 'rawx'})
        self.assertError(resp, 404, 404)

    def test_choose_2(self):
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'rawx',
                                        'size': 2})
        self.assertEqual(resp.status_code, 200)
        parsed = resp.json()
        self.assertIsInstance(parsed, list)
        self.assertEqual(2, len(parsed))

    def test_choose_too_much(self):
        if len(self.conf['services']['rawx']) >= 10000:
            self.skipTest("need less than 10000 rawx to run")
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'rawx',
                                        'size': 10000})
        self.assertError(resp, 500, CODE_POLICY_NOT_SATISFIABLE)

    def test_choose_wrong_type(self):
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'rowix'})
        self.assertError(resp, 404, CODE_SRVTYPE_NOTMANAGED)

    def test_choose_1_slot(self):
        self._reload()
        self.fill_slots(["fast"], 3, 8000)
        self.fill_slots(["slow"], 3, 7000)
        time.sleep(2)
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'echo',
                                        'slot': 'fast'})
        self.assertEqual(resp.status_code, 200)
        parsed = resp.json()
        self.assertIsInstance(parsed, list)
        self.assertEqual(1, len(parsed))
        self.assertGreaterEqual(parsed[0]["addr"].split(':')[1], 8000)

    def test_choose_4_slot(self):
        self._reload()
        self.fill_slots(["fast"], 3, 8000)
        self.fill_slots(["slow"], 3, 7000)
        time.sleep(2)
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'echo',
                                        'slot': 'fast',
                                        'size': 4})
        self.assertEqual(resp.status_code, 200)
        parsed = resp.json()
        self.assertIsInstance(parsed, list)
        self.assertEqual(4, len(parsed))
        self.assertGreaterEqual(int(parsed[0]["addr"].split(':')[1]), 8000)
        # the last one should not be 'fast' since there is only 3
        # and we don't want duplicates (and there is a default fallback)
        self.assertLess(int(parsed[3]["addr"].split(':')[1]), 8000)

    def test_choose_3_sameport(self):
        # Thanks to Vladimir
        self._reload()
        self.fill_sameport(3)
        time.sleep(2)
        resp = self.session.get(self._url_lb('choose'),
                                params={'type': 'echo',
                                        'size': 3})
        self.assertEqual(resp.status_code, 200)
        parsed = resp.json()
        self.assertIsInstance(parsed, list)
        self.assertEqual(3, len(parsed))


class TestLbPoll(BaseLbTest):

    def test_poll_invalid(self):
        resp = self.session.post(self._url_lb('poll'),
                                 params={'policy': 'invalid'})
        self.assertError(resp, 500, CODE_POLICY_NOT_SATISFIABLE)

    def _test_poll_policy(self, pol_name, count, json=None):
        resp = self.session.post(self._url_lb('poll'),
                                 params={'policy': pol_name},
                                 json=json)
        parsed = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(parsed, list)
        self.assertEqual(count, len(parsed))
        self.assertIsInstance(parsed[0], dict)
        return parsed

    def test_poll_single(self):
        self._test_poll_policy('SINGLE', 1)

    def test_poll_threecopies(self):
        if len(self.conf['services']['rawx']) < 3:
            self.skipTest("need at least 3 rawx to run")
        self._test_poll_policy('THREECOPIES', 3)

    def test_poll_ec(self):
        if len(self.conf['services']['rawx']) < 9:
            self.skipTest("need at least 9 rawx to run")
        self._test_poll_policy('EC', 9)

    def test_poll_ec_avoid(self):
        if len(self.conf['services']['rawx']) < 10:
            self.skipTest("need at least 10 rawx to run")
        svcs = self._test_poll_policy('EC', 9)
        excluded_id = svcs[0]["id"]
        data = {"avoid": [str(excluded_id)]}
        svcs2 = self._test_poll_policy('EC', 9, data)
        self.assertNotIn(excluded_id,
                         (svc["id"] for svc in svcs2))

    def test_poll_ec_known_1(self):
        if len(self.conf['services']['rawx']) < 9:
            self.skipTest("need at least 9 rawx to run")
        svcs = self._test_poll_policy('EC', 9)
        known_id = svcs[0]["id"]
        data = {"known": [str(known_id)]}
        svcs2 = self._test_poll_policy('EC', 8, data)
        self.assertNotIn(known_id, (svc["id"] for svc in svcs2))

    def test_poll_ec_known_5(self):
        if len(self.conf['services']['rawx']) < 9:
            self.skipTest("need at least 9 rawx to run")
        svcs = self._test_poll_policy('EC', 9)
        known_ids = [str(svcs[i]["id"]) for i in range(5)]
        data = {"known": known_ids}
        svcs2 = self._test_poll_policy('EC', 4, data)
        self.assertNotIn(known_ids, (svc["id"] for svc in svcs2))
