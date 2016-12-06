from jsonrpc import JsonRpcServer
import jsonrpc


class CrwJsonRpc(JsonRpcServer):
    def __init__(self, user_database):
        self.user_database = user_database

    def echo(self, s):
        return s

    def create_account(self, email, password):
        try:
            self.user_database.add_user(email, password)
            return True
        except ValueError, e:
            raise error_account_already_exists


error_account_already_exists = jsonrpc.RPCError(
    1, """There is already an account associated
    with this email""")