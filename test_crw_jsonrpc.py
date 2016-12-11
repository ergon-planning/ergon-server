import unittest as u
import database as d
import crw_jsonrpc as e
import jsonrpc
import json
import string

# Before testing, make an empty database named userdatabasetest and
# create an file named test_database.properties with one line in the
# same folder as this file, the name of the account you created the
# database under..
with open('test_database.properties') as propFile:
    user = propFile.read().splitlines()[0]
DATABASE = 'userdatabasetest'
print 'Testing with database ' + DATABASE + ' with the user ' + user


class CrwJsonRpcTest(u.TestCase):
    def setUp(self):
        self.db = d.Database(DATABASE, user)
        self.udb = d.UserDatabase(self.db)
        self.USERS = [('kees@kmail.com', 'hunter4'),
                      ('a', 'b'),
                      ('', 'b'),
                      ('ab', ''),
                      ('a\';DROP TABLE users; -- ',
                       'a\';DROP TABLE users; -- '),
                      ('henk@email.com', 'phenk'),
                      ('kees@email.com', 'pkees'),
                      ('jan@email.com', 'pjan'),
                      ('Jan@email.com', 'pjan')]
        self.db.init_database()
        self.populate_database()
        self.rpc = e.CrwJsonRpc(self.db)

    def tearDown(self):
        self.db.drop_all_tables()
        self.db.close_database_connection()

    def populate_database(self):
        """Populates the database with the users saved in the USERS
        array, by calling self.db.add_user for each."""
        for user in self.USERS:
            self.udb.add_user(user[0], user[1])

    def test_generate_correct_response(self):
        rpc_request = """{"jsonrpc": "2.0", "method": "echo",
                        "params": [true], "id": 1}"""
        rpc_response = self.rpc.rpc_invoke(rpc_request)
        response_obj = json.loads(rpc_response)

        self.assertTrue('jsonrpc' in response_obj,
                        """Test that a jsonrpc field is included in
                        the response.""")
        self.assertEquals(response_obj['jsonrpc'], self.rpc.version,
                          """Test that the jsonrpc field includes the
                          correct jsonrpc version""")

        self.assertTrue('id' in response_obj,
                        """Test that an id field is included in
                        the response""")
        self.assertEquals(response_obj['id'], 1,
                          """Test that an id corresponding to the
                          request id is included in the response""")

        self.assert_result_equals(rpc_response,  True,
                                  """Test that the response includes a
                                  result field""")

    def test_create_correct_account(self):
        rpc_request = """{"jsonrpc": "2.0", "method": "create_account",
                        "params": ["nieuw@email.com", "hunter4"],
                        "id": 2}"""
        rpc_response = self.rpc.rpc_invoke(rpc_request)
        response_obj = json.loads(rpc_response)

        self.assertTrue('result' in response_obj,
                        """Test that the response contains a
                        result""")
        self.assertEquals(response_obj['result'], True,
                          """Test that the response contains True as
                          result when a correct create_account request
                          has been invoked""")

        self.assertTrue(self.udb.verify_user('nieuw@email.com',
                                             'hunter4'),
                        """Test that the account has been saved
                        correctly in the database and the user
                        can be verified using the supplied
                        credentials.""")

    def test_create_duplicate_account(self):
        rpc_request = """{"jsonrpc": "2.0", "method": "create_account",
                        "params": ["henk@email.com", "password"],
                        "id": 2}"""
        rpc_response = self.rpc.rpc_invoke(rpc_request)

        self.assert_error_equals(rpc_response, 1,
                                 """Test that creating a duplicate
                                 account returns a
                                 error_account_already_exists.""")

    def assert_result_equals(self, response, expected_result, message):
        """Asserts that a result exists in the response and that the
        result is equal to the expected_result."""
        response_obj = json.loads(response)
        self.assertTrue('result' in response_obj, """Assert that the
        response has a result""")
        self.assertEquals(response_obj['result'], expected_result,
                          message)

    def assert_error_equals(self, response, expected_error_code, message):
        """Asserts that an error exists in the response and that the
        error code is equal to the expected error code."""
        response_obj = json.loads(response)
        self.assertTrue('error' in response_obj,
                        """Assert that the response has an error""")
        self.assertEquals(response_obj['error']['code'],
                          expected_error_code, message)

    def assert_contains_only_characters(self, s, allowed_characters,
                                        message):
        # Check that the session keys only contains allowed
        # characters. See http://stackoverflow.com/a/1323374 for how
        # this works.
        self.assertTrue(set(session_key) <= set(allowed_characters),
                        message)

    def test_login_valid_user_valid_session_key(self):
        (email, password) = self.USERS[0]
        session_key = self.rpc.login(email, password)

        allowed_characters = string.ascii_letters + string.digits
        self.assert_contains_only_characters
        (session_key, allowed_characters,
         """Test that the generated session key
         contains only allowed characters.""")

    def test_login_invalid_password(self):
        """Test that attempting to login with an invalid password
        raises an invalid account credentials RPCError"""
        with self.assertRaises(jsonrpc.RPCError) as err:
            self.rpc.login(self.USERS[0][0], 'incorrectpassword')
        self.assertEquals(err.exception.code, 2)

    def test_login_invalid_email(self):
        """Test that attempting to login with an invalid email
        raises an invalid account credentials RPCError"""
        with self.assertRaises(jsonrpc.RPCError) as err:
            self.rpc.login('nonexistingemail', self.USERS[0][1])
        self.assertEquals(err.exception.code, 2)

    def generate_rpc_request(self, method, params):
        """Creates an JSON RPC request. Method and params should be
        strings."""
        return '{"jsonrpc": "2.0", "method": "' + method + '",' +\
            '"params": ' + params + ', "id": 2}'

    def test_login_valid_request(self):
        (email, password) = self.USERS[0]
        request = self.generate_rpc_request("login", '["{}","{}"]'.
                                            format(email, password))
        response = self.rpc.rpc_invoke(request)
        r_obj = json.loads(response)
        allowed_characters = string.ascii_letters + string.digits
        self.assert_contains_only_characters
        (r_obj['result'], allowed_characters,
         """Test that the generated session key
         contains only allowed characters.""")


if __name__ == '__main__':
    suite = u.TestLoader()\
                    .loadTestsFromTestCase(CrwJsonRpcTest)
    u.TextTestRunner(verbosity=2).run(suite)
