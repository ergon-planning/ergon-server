from jsonrpc import JsonRpcServer
import jsonrpc
import database as d
import datetime


# CrwJsonRpc is a server that accepts an extended version of JsonRpc
# 2.0 requests, it supports the 'session' and 'user_id' values in the
# request and those are required in any requests which need the user
# to be logged in. CrwJsonRpc will return standard JsonRpc 2.0
# responses.
class CrwJsonRpc(JsonRpcServer):
    def __init__(self, database):
        self.udb = d.UserDatabase(database)
        self.tdb = d.TeamDatabase(database)
        self.sdb = d.SessionDatabase(database)
        self.hdb = d.HealthDatabase(database)
        self.trdb = d.TrainingDatabase(database)
        self.idb = d.IntervalDatabase(database)

        # The id of the user who's request is currently being processed
        self.current_user_id = -1
        # Stores whether the user is authenticated for the user id
        # currently
        self.authenticated = False

    # We overwrite the rpc_invoke_single method to save our custom
    # values before calling the rpc_invoke_single method from the
    # super class.
    def rpc_invoke_single(self, data):
        try:
            if type(data) is dict:
                if 'session' in data:
                    # The user can be authenticated if they
                    # supply both an session key and user id (and they
                    # are both correct).
                    # Or if they supply a correct session_key. The user_id
                    # that belongs to that session_key will be used then.
                    if 'user_id' in data and data['user_id'] is not None:
                        self.current_user_id = data['user_id']
                    else:
                        self.current_user_id =\
                            self.sdb.get_user_id_by_sessionkey(
                                data['session'])

                    if self.current_user_id is None:
                        self.current_user_id = -1
                    else:
                        self.authenticated = self.sdb.verify_session_key(
                            self.current_user_id, data['session'])
                        self.current_session = data['session']

                    if self.authenticated:
                        self.sdb.renew_session_key(
                            self.current_user_id, data['session'])

            response = JsonRpcServer.rpc_invoke_single(self, data)
        except Exception as e:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": RPCError.internal_error(e).serialize()
            }
        finally:
            self.current_user_id = -1
            self.authenticated = False

            return response

    def echo(self, s):
        return s

    def create_account(self, email, password):
        self.check_arguments_not_none([email, password])

        try:
            self.udb.add_user(email, password)
            return True
        except d.PasswordFieldEmpty, e:
            raise error_no_password_submitted
        except d.UserDoesNotExistError, e:
            raise error_account_already_exists
        except ValueError, e:
            raise error_invalid_email_address

    def login(self, email, password):
        """This function will verify the user and return a new session
        key if the user has been authenticated correctly."""
        self.check_arguments_not_none([email, password])

        if (not self.udb.does_user_email_exist(email)) or\
           (not self.udb.verify_user(email, password)):
            raise error_invalid_account_credentials

        return self.sdb.generate_session_key(
            self.udb.get_user_id(email))

    def user_status(self):
        """Returns if the user is still authenticated, if the user is
        in a team and if the user is a coach in the form:

        (authenticated, is_in_team, is_coach)"""
        if not self.authenticated or\
           not self.udb.does_user_exist(self.current_user_id):
            return (False, False, False)
        else:
            user_status = self.udb.get_user_team_status(
                self.current_user_id)

            return (self.authenticated,
                    user_status[0] is not None,
                    user_status[1] is not None and user_status[1])

    def logout(self):
        """Removes user's active session from the session database"""
        if not self.authenticated:
            raise error_incorrect_authentication

        self.sdb.remove_session_key(self.current_session)

        return True

    def logged_in(self):
        """Returns the user's authenticating status and coach status"""
        (team_id, coach) = self.udb.get_user_team_status(
            self.current_user_id)

        return (self.authenticated, coach)

    def create_team(self, team_name):
        """Creates a team with the user of user_id as an coach.
        Returns the team_id of the created team."""
        self.check_arguments_not_none([team_name])

        if not self.authenticated:
            raise error_incorrect_authentication

        return self.tdb.create_team(self.current_user_id, team_name)

    def add_to_team(self, user_to_add_email):
        """Adds the user with user_to_add_email to the team that the user
        is in."""
        self.check_arguments_not_none([user_to_add_email])

        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, coach) = self.udb.get_user_team_status(
            self.current_user_id)
        if (team_id is None or coach is None or not coach):
            raise error_invalid_action_no_coach

        try:
            user_to_add_id = self.udb.get_user_id(user_to_add_email)
        except d.UserDoesNotExistError:
            raise error_user_does_not_exist

        self.tdb.add_user_to_team(self.current_user_id, user_to_add_id)

        return True

    def remove_from_team(self, user_to_remove_email):
        """Removes the user with user_to_remove_email from the team that the user
        is in."""
        self.check_arguments_not_none([user_to_remove_email])

        if not self.authenticated:
            raise error_incorrect_authentication

        try:
            user_to_remove_id = self.udb.get_user_id(user_to_remove_email)
            self.tdb.remove_user_from_team(self.current_user_id,
                                           user_to_remove_id)
            return True
        except d.UserDoesNotExistError, e:
            raise error_user_does_not_exist
        except d.ActionNotPermittedError, e:
            raise error_invalid_action_no_coach

    def set_coach_status(self, user_to_change_email, coach):
        """Changes the coach property of the user with the email
        `user_to_change_email` to `coach`. It can only be used by a
        coach of a team on a member of that same team. It can not be
        used to change the last coach of a team to a regular member.

        This can be used to remove coach status from the user him or
        herself.

        """
        self.check_arguments_not_none([user_to_change_email, coach])

        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, caller_coach) = self.udb.get_user_team_status(
            self.current_user_id)
        if not caller_coach or team_id is None:
            raise error_invalid_action_no_coach

        coaches_in_team =\
            len([member for member in
                 self.tdb.get_team_members(team_id)
                 if member[2]])

        try:
            user_to_change = self.udb.get_user_id(user_to_change_email)
        except d.UserDoesNotExistError, e:
            raise error_user_does_not_exist

        if coaches_in_team == 1 and user_to_change == self.current_user_id \
           and not coach:
            # This RPC call is attempting to remove the only coach that is left
            # in this team, which is not allowed.
            raise error_invalid_action_last_coach

        self.tdb.set_user_coach_status(user_to_change, coach)

        return True

    def my_team_info(self):
        """Returns the team id, team name and members with user id,
        email and coach status of the team the user is in."""
        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, coach) = self.udb.get_user_team_status(
            self.current_user_id)
        if (team_id is None):
            raise error_user_is_not_in_a_team

        team_name = self.tdb.get_team_name(team_id)
        team_members = self.tdb.get_team_members(team_id)
        return [team_id, team_name] + team_members

    def add_health_data(self, date, resting_heart_rate, weight, comment):
        """Adds the health data of the logged in user to the health
        database using HealthDatabase::add_health_data.

        Returns true on success"""
        self.check_arguments_not_none([date, resting_heart_rate,
                                       weight])

        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, coach) = self.udb.get_user_team_status(self.current_user_id)
        if team_id is not None and coach:
            # Someone who is a coach in a team, can't add any health
            # data
            raise error_invalid_action_coach

        self.hdb.add_health_data(
            self.current_user_id, date, resting_heart_rate,
            weight, comment)

        return True

    def get_my_health_data(self, days_in_the_past):
        """Gets the health data of the user from `days_in_the_past` ago to
        now, in the form [(date, resting_heart_rate, weight,
        comment)].

        `days_in_the_past` should be an int.
        """
        self.check_arguments_not_none([days_in_the_past])

        if not self.authenticated:
            raise error_incorrect_authentication

        return self.hdb.get_past_health_data(
            self.current_user_id, datetime.timedelta(days=days_in_the_past))

    def get_team_health_data(self, days_in_the_past):
        """RPC to get the health data of their whole team. It returns
        [(member_email, [(date, resting_heart_rate, weight, comment)])].

        The user should be authenticated and a coach.

        `days_in_the_past` should be an int."""
        self.check_arguments_not_none([days_in_the_past])

        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, coach) = self.udb.get_user_team_status(self.current_user_id)
        if not coach or team_id is None:
            raise error_invalid_action_no_coach

        # This is a list in the form [(user_id, email, coach)]
        team_list = self.tdb.get_team_members(team_id)

        team_health_data = []

        for team_member in team_list:
            coach = team_member[2]
            if coach:
                # Coaches don't have any health data and can be skipped
                continue
            email = team_member[1]
            user_id = team_member[0]
            team_health_data.append(
                (email,
                 self.hdb.get_past_health_data(
                     user_id, datetime.timedelta(days=days_in_the_past))))

        return team_health_data

    def add_training(self, time, type_is_ed, comment, interval_list):
        """Adds a new training for the user with associated interval(s)
        supplied in the interval_list. interval_list must be in the form
        [(duration, power, pace, rest)] with rest as seconds.

        Returns true on success"""
        self.check_arguments_not_none([time, type_is_ed, interval_list])

        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, coach) = self.udb.get_user_team_status(self.current_user_id)
        if team_id is not None and coach:
            # Someone who is a coach in a team, can't add any training
            # data
            raise error_invalid_action_coach

        training_id = self.trdb.add_training(
            self.current_user_id, time, type_is_ed, comment)

        for interval in interval_list:
            duration = interval[0]
            power = interval[1]
            pace = interval[2]
            rest = interval[3]

            # Pace is explicitly allowed to be None
            self.check_arguments_not_none([duration, power, rest])

            self.idb.add_interval(training_id, duration, power, pace, rest)

        return True

    def get_my_training_data(self, days_in_the_past):
        """Returns training data with interval data from days_in_the_past
        to now, in the form
        [(time, type_is_ed, comment, [(duration, power, pace, rest)])] """
        self.check_arguments_not_none([days_in_the_past])

        if not self.authenticated:
            raise error_incorrect_authentication

        # This list is in the form [(training_id, time, type_is_ed, comment)]
        past_trainings = self.trdb.get_past_training_data(
            self.current_user_id,
            datetime.timedelta(days=days_in_the_past))

        training_data = []

        for training in past_trainings:
            training_id = training[0]
            time = training[1]
            type_is_ed = training[2]
            comment = training[3]
            # This list is in the form [(duration, power, pace, rest)]
            interval_data = self.idb.get_training_interval_data(training_id)
            training_data.append((time, type_is_ed, comment, interval_data))

        return training_data

    def get_team_training_data(self, days_in_the_past):
        """RPC to get the training data of their whole team with the interval
        data. It returns:
        [(member_email,
            [(time, type_is_ed, comment,
                [(duration, power, pace, rest)]
             )]
         )]

        The user should be authenticated and a coach.

        `days_in_the_past` should be an int.
        """
        self.check_arguments_not_none([days_in_the_past])

        if not self.authenticated:
            raise error_incorrect_authentication

        (team_id, coach) = self.udb.get_user_team_status(self.current_user_id)
        if not coach or team_id is None:
            raise error_invalid_action_no_coach

        # This is a list in the form [(user_id, email, coach)]
        team_list = self.tdb.get_team_members(team_id)

        team_training_data = []

        for (user_id, email, coach) in team_list:
            if coach:
                # Choaches don't have any training data, they just
                # watch it.
                continue

            past_trainings = self.trdb.get_past_training_data(
                user_id, datetime.timedelta(days=days_in_the_past))

            member_training_data = []

            for training in past_trainings:
                training_id = training[0]
                time = training[1]
                type_is_ed = training[2]
                comment = training[3]
                # This list is in the form [(duration, power, pace, rest)]
                interval_data = self.idb.get_training_interval_data(
                    training_id)
                member_training_data.append(
                    (time, type_is_ed, comment, interval_data))

            team_training_data.append((email, member_training_data))

        return team_training_data

    def check_arguments_not_none(self, list_of_arguments):
        """Accepts a list of arguments that can't be None. Raises an
        error_mandatory_argument_none when any of these is None."""
        for argument in list_of_arguments:
            if argument is None:
                raise error_mandatory_argument_none


error_account_already_exists = jsonrpc.RPCError(
    1, """There is already an account associated"""
    """with this email""")
error_invalid_account_credentials = jsonrpc.RPCError(
    2, """The provided credentials are incorrect""")
error_incorrect_authentication = jsonrpc.RPCError(
    3, """The server was not able to authenticate the user, the"""
    """session or the user_id is missing or incorrect or expired.""")
error_no_password_submitted = jsonrpc.RPCError(
    4, """No password is entered""")
error_invalid_action_no_coach = jsonrpc.RPCError(
    5, """The user is not a coach in a team, so they can't perform"""
    """this action""")
error_user_is_not_in_a_team = jsonrpc.RPCError(
    6, """The user is not in a team""")
error_user_does_not_exist = jsonrpc.RPCError(
    7, """"No user with that value exists""")
error_invalid_action_coach = jsonrpc.RPCError(
    8, """The user is a coach in a team, so they can't perform"""
    """this action""")
error_invalid_action_last_coach = jsonrpc.RPCError(
    9, """Removing the last coach is a team is not allowed""")
error_invalid_email_address = jsonrpc.RPCError(
    10, """The given email address is synthactically invalid.""")
error_mandatory_argument_none = jsonrpc.RPCError(
    11, """One of the mandatory arguments was None.""")
